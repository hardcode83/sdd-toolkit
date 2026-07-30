#!/usr/bin/env python3
"""Rebuild a change's usage ledger from the captured OTel log, and consolidate.

`usage-phase.sh` writes one ledger row when a phase asks it to. Everything it
never gets asked about is lost from the ledger even though the sink captured it:
a phase interrupted before its gate, a phase whose skill has no metrics call, or
the spend that arrives after the gate already wrote its row. The datapoints are
still in `.sdd-usage/otel.jsonl`, tagged with `<feature>/<phase>`, so the ledger
can always be recomputed from them.

    sync <feature>     rebuild the ledger and upsert the consolidated row
    report             list features whose captured spend never reached a ledger

`sync` works on active and archived changes alike, which makes it the recovery
path for history written before a phase was instrumented. It never lowers a
recorded value it cannot explain: rows the log knows nothing about are kept
verbatim, and a row already holding more than the log accounts for is preserved
and reported instead of being overwritten.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path


LEDGER_HEADER = (
    "| date | phase | models | tokens in | tokens out | tokens cache | "
    "cost USD (est) | notes |\n|---|---|---|---|---|---|---|---|\n"
)
SUMMARY_HEADER = (
    "| feature | phases | tokens in | tokens out | tokens cache | "
    "cost USD (est) | started | archived |\n|---|---|---|---|---|---|---|---|\n"
)
LEDGER_ROW_RE = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+?)\s*\|")
CACHE_TYPES = {"cacheRead", "cacheCreation"}
# A recorded row is only "more than the log explains" when the gap is material.
# Rows store four decimals, so sub-cent rounding must not look like lost data.
MATERIAL_COST = 0.01
ARCHIVE_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")


class UsageError(RuntimeError):
    """Actionable failure."""


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def read_number(value: str) -> float:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return 0.0


class PhaseTotals:
    """What one phase consumed, per the log."""

    def __init__(self) -> None:
        self.tokens = {"input": 0.0, "output": 0.0, "cache": 0.0}
        self.cost = 0.0
        self.models: set[str] = set()
        self.subagent_rows = 0
        self.first_ts: int | None = None
        self.last_ts: int | None = None

    def add(self, row: dict) -> None:
        value = float(row.get("value") or 0)
        if row.get("metric") == "tokens":
            kind = row.get("type")
            if kind in CACHE_TYPES:
                self.tokens["cache"] += value
            elif kind in self.tokens:
                self.tokens[kind] += value
        elif row.get("metric") == "cost":
            self.cost += value
        if row.get("model"):
            self.models.add(str(row["model"]))
        if row.get("source") == "subagent":
            self.subagent_rows += 1
        timestamp = row.get("ts")
        if isinstance(timestamp, (int, float)):
            stamp = int(timestamp)
            self.first_ts = stamp if self.first_ts is None else min(self.first_ts, stamp)
            self.last_ts = stamp if self.last_ts is None else max(self.last_ts, stamp)

    def row(self, phase: str) -> str:
        day = (
            datetime.fromtimestamp(self.first_ts).strftime("%Y-%m-%d")
            if self.first_ts
            else date.today().isoformat()
        )
        note = "incl. subagents" if self.subagent_rows else ""
        return (
            f"| {day} | {phase} | {' '.join(sorted(self.models)) or '?'} | "
            f"{round(self.tokens['input'])} | {round(self.tokens['output'])} | "
            f"{round(self.tokens['cache'])} | {self.cost:.4f} | {note} |\n"
        )


def load_log(root: Path) -> list[dict]:
    log = root / ".sdd-usage" / "otel.jsonl"
    if not log.is_file():
        return []
    rows: list[dict] = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue  # a truncated tail must not lose the rest of the history
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def totals_by_feature(rows: list[dict]) -> dict[str, dict[str, PhaseTotals]]:
    features: dict[str, dict[str, PhaseTotals]] = {}
    for row in rows:
        task = str(row.get("task") or "")
        if "/" not in task:
            continue  # untagged spend cannot be attributed to a phase
        feature, phase = task.split("/", 1)
        phases = features.setdefault(feature, {})
        phases.setdefault(phase, PhaseTotals()).add(row)
    return features


def find_change(root: Path, feature: str) -> tuple[Path, str | None]:
    """Return the change directory and its archive date, if archived."""
    active = root / "sdd" / "changes" / feature
    if active.is_dir():
        return active, None
    archive = root / "sdd" / "changes" / "archive"
    matches = sorted(archive.glob(f"????-??-??-{feature}")) if archive.is_dir() else []
    if len(matches) > 1:
        raise UsageError(f"Multiple archived changes match '{feature}'.")
    if matches:
        match = ARCHIVE_DATE_RE.match(matches[0].name)
        return matches[0], match.group(1) if match else None
    raise UsageError(
        f"No change '{feature}' under sdd/changes/ or sdd/changes/archive/."
    )


def existing_rows(ledger: Path) -> dict[str, str]:
    if not ledger.is_file():
        return {}
    rows: dict[str, str] = {}
    for line in ledger.read_text(encoding="utf-8", errors="replace").splitlines(True):
        match = LEDGER_ROW_RE.match(line)
        if match:
            rows.setdefault(match.group(2), line if line.endswith("\n") else line + "\n")
    return rows


def row_cost(line: str) -> float:
    parts = cells(line)
    return read_number(parts[6]) if len(parts) >= 7 else 0.0


def sync_ledger(
    change: Path, feature: str, phases: dict[str, PhaseTotals]
) -> tuple[list[str], list[str]]:
    """Merge log-derived rows into the ledger. Returns (rows, warnings)."""
    ledger = change / "metrics.md"
    recorded = existing_rows(ledger)
    warnings: list[str] = []
    merged: dict[str, str] = {}

    for phase, totals in phases.items():
        candidate = totals.row(phase)
        previous = recorded.get(phase)
        # Never lower a recorded value the log cannot account for: an older row
        # may have been written from datapoints this log no longer contains.
        if previous and row_cost(previous) - totals.cost > MATERIAL_COST:
            warnings.append(
                f"{feature}/{phase}: ledger holds ${row_cost(previous):.4f} but the log "
                f"accounts for ${totals.cost:.4f} — keeping the recorded row"
            )
            merged[phase] = previous
        else:
            merged[phase] = candidate
    for phase, line in recorded.items():
        merged.setdefault(phase, line)

    ordered = sorted(
        merged.items(),
        key=lambda item: (
            phases[item[0]].first_ts
            if item[0] in phases and phases[item[0]].first_ts
            else 0,
            cells(item[1])[0],
            item[0],
        ),
    )
    rows = [line for _, line in ordered]
    ledger.write_text(f"# Metrics: {feature}\n\n{LEDGER_HEADER}" + "".join(rows), encoding="utf-8")
    return rows, warnings


def summarize(rows: list[str]) -> tuple[list[str], list[float], str]:
    phases: list[str] = []
    totals = [0.0, 0.0, 0.0, 0.0]
    started = ""
    for line in rows:
        parts = cells(line)
        if len(parts) < 7:
            continue
        phases.append(parts[1])
        for index in range(4):
            totals[index] += read_number(parts[3 + index])
        started = min(started, parts[0]) if started else parts[0]
    return phases, totals, started


def upsert_summary(
    root: Path, feature: str, rows: list[str], archived: str | None
) -> None:
    summary = root / "sdd" / "metrics.md"
    phases, totals, started = summarize(rows)
    line = (
        f"| {feature} | {', '.join(phases)} | {round(totals[0])} | {round(totals[1])} | "
        f"{round(totals[2])} | {totals[3]:.4f} | {started or '—'} | {archived or '—'} |\n"
    )
    if not summary.is_file():
        summary.write_text(f"# SDD Metrics\n\n{SUMMARY_HEADER}{line}", encoding="utf-8")
        return
    output: list[str] = []
    replaced = False
    for existing in summary.read_text(encoding="utf-8", errors="replace").splitlines(True):
        parts = cells(existing)
        if len(parts) == 8 and parts[0] == feature:
            output.append(line)
            replaced = True
        else:
            output.append(existing)
    if not replaced:
        if output and not output[-1].endswith("\n"):
            output[-1] += "\n"
        output.append(line)
    summary.write_text("".join(output), encoding="utf-8")


def sync(root: Path, feature: str) -> int:
    log_rows = load_log(root)
    if not log_rows:
        print("usage tracking not enabled (no .sdd-usage/otel.jsonl) — skipping")
        return 0
    change, archived = find_change(root, feature)
    phases = totals_by_feature(log_rows).get(feature, {})
    rows, warnings = sync_ledger(change, feature, phases)
    if not rows:
        print(f"no usage captured for '{feature}' — nothing to sync")
        return 0
    upsert_summary(root, feature, rows, archived)
    _, totals, _ = summarize(rows)
    for warning in warnings:
        print(f"WARNING: {warning}")
    print(
        f"synced {feature}: {len(rows)} phase row(s), "
        f"in={round(totals[0])} out={round(totals[1])} cache={round(totals[2])} "
        f"≈${totals[3]:.4f} → {(change / 'metrics.md').relative_to(root)} + sdd/metrics.md"
    )
    return 0


def report(root: Path) -> int:
    log_rows = load_log(root)
    if not log_rows:
        print("usage tracking not enabled (no .sdd-usage/otel.jsonl) — nothing to report")
        return 0
    features = totals_by_feature(log_rows)
    untagged = sum(
        float(item.get("value") or 0)
        for item in log_rows
        if item.get("metric") == "cost" and "/" not in str(item.get("task") or "")
    )
    gaps = 0
    for feature in sorted(features):
        try:
            change, _ = find_change(root, feature)
        except UsageError:
            print(f"{feature}: captured but no change directory exists")
            gaps += 1
            continue
        recorded = existing_rows(change / "metrics.md")
        missing = [phase for phase in features[feature] if phase not in recorded]
        captured = sum(totals.cost for totals in features[feature].values())
        ledger_cost = sum(row_cost(line) for line in recorded.values())
        if missing or captured - ledger_cost > 0.01:
            gaps += 1
            detail = f"missing phases: {', '.join(sorted(missing))}" if missing else "row values behind the log"
            print(
                f"{feature}: captured ≈${captured:.4f}, ledger ≈${ledger_cost:.4f} — {detail}"
            )
    if untagged > 0.01:
        print(f"(≈${untagged:.4f} captured with no feature/phase tag — unattributable)")
    print(f"usage report: {gaps} feature(s) need `usage-sync.py sync <feature>`")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sync_parser = sub.add_parser("sync")
    sync_parser.add_argument("feature")
    sub.add_parser("report")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        return sync(root, args.feature) if args.command == "sync" else report(root)
    except UsageError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
