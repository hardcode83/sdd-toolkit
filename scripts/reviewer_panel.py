#!/usr/bin/env python3
"""Executable lifecycle gate for the shared reviewer panel.

Runtime skills perform spawning; this command is the deterministic boundary
that plans the expected set and validates collected JSON before lifecycle
annotation or certification commands are allowed to run.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# Phases whose gate certifies a whole change: their verdict is persisted as a
# receipt the lifecycle reads (ADR 0007). `run` certifies one section and keeps
# its record in tasks.md (`panel: PASS`), so it writes none.
RECEIPT_PHASES = {"review", "auto"}
# A section's receipt sits next to the feature's: <feature>-run-<section>.json.
SECTION_HEADING_RE = re.compile(r"^(## (\d+)\.[^\n]*?)(\s*<!--\s*panel:[^>]*-->)?\s*$")
EPILOG = """
Shapes the gate accepts (build them from `--plan`, never by reading this file):

  --scope   '{"feature": "<f>", "scope_id": "run:<f>:<N>", "files": ["src/a.py", ...]}'
            (`scope_id` is free text; use run:<feature>:<section> per section and
             review:<feature> at feature scale; `files` is the diff's file list)
  --results '[{"invocation_id": "<Agent tool_use id>", "reviewer_id": "sdd-qa",
               "payload": {"reviewer_id": "sdd-qa", "scope_id": "run:<f>:<N>", "lens": "qa",
                           "verdict": "PASS", "findings": [], "evidence": ["src/a.py"],
                           "status": "complete"}}, ...]'
            (one envelope per planned reviewer; `payload` is the reviewer's final JSON)

  --plan    prints the planned reviewers for the scope and an example --results,
            and exits without evaluating anything.
  --section N   (phase run) writes the section's receipt and, on PASS, annotates
            the `## N.` heading of tasks.md itself — the orchestrator never does.
"""
# Paths whose change never invalidates a reviewer's PASS on the code: the
# review documents themselves, docs, and images. Anything else is code.
NON_CODE_RE = re.compile(r"^(sdd/|docs/)|\.(md|txt|svg|png|jpg|jpeg|gif)$", re.IGNORECASE)

MODULE = Path(__file__).resolve().parents[1] / "skills" / "reviewer-panel" / "reviewer_plan.py"
import importlib.util
spec = importlib.util.spec_from_file_location("sdd_reviewer_plan_cli", MODULE)
assert spec and spec.loader
reviewer_plan = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reviewer_plan
spec.loader.exec_module(reviewer_plan)


def git_out(args: list[str], cwd: Path) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def receipt_path(root: Path, feature: str, section: int | None = None) -> Path | None:
    """`<git common dir>/sdd/receipts/<feature>.json` (or `<feature>-run-<N>.json`).

    Machine-local state next to the session registry: every worktree of the
    clone sees it, `git status` never does — a file inside `sdd/changes/` would
    dirty the tree the STATE-only lifecycle commit demands clean.
    """
    common = git_out(["rev-parse", "--git-common-dir"], root)
    if common is None:
        return None
    name = f"{feature}.json" if section is None else f"{feature}-run-{section}.json"
    return (root / common).resolve() / "sdd" / "receipts" / name


def annotate_section(tasks: Path, section: int, marker: str) -> bool:
    """Set the `<!-- panel: … -->` marker on the `## N.` heading, keeping any other
    marker (`<!-- hard -->`) in place. Returns whether a heading was found."""
    if not tasks.is_file():
        return False
    lines = tasks.read_text(encoding="utf-8").splitlines(keepends=True)
    done = False
    for index, line in enumerate(lines):
        match = SECTION_HEADING_RE.match(line.rstrip("\n"))
        if not match or int(match.group(2)) != section:
            continue
        lines[index] = f"{match.group(1).rstrip()} {marker}\n"
        done = True
        break
    if done:
        tasks.write_text("".join(lines), encoding="utf-8")
    return done


def write_receipt(root: Path, feature: str, phase: str, scope: dict, panel, head: str | None,
                  section: int | None = None) -> tuple[Path | None, str | None, bool]:
    """Persist the gate's verdict next to the change, one reviewer per row.

    A fresh fork cannot remember which reviewers already passed; the receipt
    can. It carries the PASS payloads so `--carry` can reuse them when only
    non-code changed, and the HEAD they were evaluated at so `mark-local-verified`
    can refuse a certification that does not describe the current commit.
    """
    change = root / "sdd" / "changes" / feature
    path = receipt_path(root, feature, section if phase == "run" else None)
    if not change.is_dir() or path is None or (phase == "run" and section is None):
        return None, None, False
    reviewers = []
    for result in panel.results:
        row = {
            "reviewer_id": result.reviewer_id, "lens": result.lens, "verdict": result.verdict,
            "status": result.status, "collection_status": result.collection_status,
            "findings": len(result.findings) if isinstance(result.findings, list) else None,
        }
        if result.verdict == "PASS" and result.status == "complete":
            row["payload"] = {"reviewer_id": result.reviewer_id, "scope_id": result.scope_id,
                              "lens": result.lens, "verdict": "PASS", "findings": [],
                              "evidence": list(result.evidence), "status": "complete"}
        reviewers.append(row)
    receipt = {"schema": 1, "phase": phase, "feature": feature, "scope_id": scope.get("scope_id"),
               "section": section, "sha": head,
               "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "gate": panel.gate, "errors": list(panel.errors), "reviewers": reviewers}
    import hashlib
    receipt_id = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    receipt["id"] = receipt_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    annotated = False
    if phase == "run" and section is not None and panel.gate == "PASS":
        # The gate is the only writer of its own verdict: a hand-written
        # `panel: PASS` is indistinguishable from a real one otherwise (ADR 0008).
        marker = f"<!-- panel: PASS {time.strftime('%Y-%m-%d', time.gmtime())} receipt:{receipt_id} -->"
        annotated = annotate_section(change / "tasks.md", section, marker)
    return path, receipt_id, annotated


def carried_envelopes(receipt: dict, plan, present: set[str], feature: str, phase: str,
                      head: str | None, git_cwd: Path) -> list[dict]:
    """PASS results a previous receipt lets this run reuse, or a ValueError.

    Reuse is legitimate only when the code the reviewer passed is the code being
    certified: the receipt's commit must be an ancestor of HEAD and the diff
    since it must touch no code path. Otherwise every reviewer runs again.
    """
    if receipt.get("feature") != feature or receipt.get("phase") not in RECEIPT_PHASES:
        raise ValueError("carry refused: the receipt belongs to another feature or phase")
    base = receipt.get("sha")
    if not base or not head:
        raise ValueError("carry refused: the receipt or HEAD has no commit to compare")
    if base != head:
        if git_out(["merge-base", "--is-ancestor", base, head], git_cwd) is None:
            raise ValueError(f"carry refused: receipt commit {base[:12]} is not an ancestor of HEAD")
        changed = (git_out(["diff", "--name-only", base, head], git_cwd) or "").splitlines()
        code = [path for path in changed if not NON_CODE_RE.search(path)]
        if code:
            raise ValueError(
                "carry refused: code changed since the receipt (" + ", ".join(code[:5])
                + ("…" if len(code) > 5 else "") + "); relaunch every reviewer"
            )
    carried = []
    for item in plan:
        if not item.required or item.reviewer_id in present:
            continue
        row = next((r for r in receipt.get("reviewers", []) if r.get("reviewer_id") == item.reviewer_id), None)
        if row and row.get("verdict") == "PASS" and isinstance(row.get("payload"), dict):
            carried.append({"invocation_id": f"carried:{base}", "reviewer_id": item.reviewer_id,
                            "payload": row["payload"], "carried_from": base})
    return carried


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--phase", choices=sorted(reviewer_plan.VALID_PHASES), required=True)
    parser.add_argument("--feature", required=True)
    parser.add_argument("--scope", required=True, help="JSON scope object (see epilog)")
    parser.add_argument("--results", help="JSON list of result envelopes (see epilog); required unless --plan")
    parser.add_argument("--plan", action="store_true", help="print the planned reviewers and an example --results, then exit")
    parser.add_argument("--section", type=int, help="(phase run) section number: writes its receipt and annotates tasks.md on PASS")
    parser.add_argument("--codex-handoff", help="JSON top-level Codex harness handoff")
    parser.add_argument("--worktree", type=Path, help="feature worktree for a Codex handoff")
    parser.add_argument("--referents", default="{}", help="JSON referent mapping for a Codex handoff")
    parser.add_argument("--baseline", help="optional harness pre-collection snapshot")
    parser.add_argument("--final-snapshot", help="optional harness post-collection snapshot")
    parser.add_argument("--solo", action="store_true")
    parser.add_argument(
        "--carry",
        action="store_true",
        help="reuse PASS verdicts from the change's previous receipt for reviewers not "
             "in --results, when only non-code changed since (a re-review after doc fixes)",
    )
    args = parser.parse_args(argv)
    try:
        scope = json.loads(args.scope)
        if not isinstance(scope, dict):
            raise ValueError("scope must be an object")
        plan = reviewer_plan.build_reviewer_plan(args.root, args.phase, scope, solo=args.solo)
        if args.plan:
            required = [item for item in plan if item.required]
            print(json.dumps({
                "phase": args.phase, "feature": args.feature, "scope_id": scope.get("scope_id"),
                "reviewers": [item.to_dict() for item in plan],
                "launch": [{"agent": item.reviewer_id, "lens": item.lens, "scope_id": item.scope_id} for item in required],
                "example_results": [{
                    "invocation_id": f"<tool_use id of the {item.reviewer_id} Agent call>",
                    "reviewer_id": item.reviewer_id,
                    "payload": {"reviewer_id": item.reviewer_id, "scope_id": item.scope_id, "lens": item.lens,
                                "verdict": "PASS", "findings": [], "evidence": list(scope.get("files", []))[:1],
                                "status": "complete"},
                } for item in required],
            }, indent=2, sort_keys=True))
            return 0
        if args.results is None:
            raise ValueError("--results is required (use --plan to see the expected shape)")
        raw_results = json.loads(args.results)
        if not isinstance(raw_results, list):
            raise ValueError("results must be a list")
        if args.phase == "run" and args.section is None:
            raise ValueError("--section N is required for phase run: the gate writes the section's receipt and annotation")
        git_cwd = args.worktree or args.root
        head = git_out(["rev-parse", "HEAD"], git_cwd)
        if args.carry and not args.solo and not args.codex_handoff:
            previous = receipt_path(args.root, args.feature)
            if previous is None or not previous.is_file():
                raise ValueError("carry refused: no previous receipt for this change")
            present = {e.get("reviewer_id") for e in raw_results if isinstance(e, dict)}
            raw_results = raw_results + carried_envelopes(
                json.loads(previous.read_text(encoding="utf-8")), plan, present,
                args.feature, args.phase, head, git_cwd,
            )
        if args.solo:
            panel = reviewer_plan.PanelResult(plan, [], "FAIL", ["solo bypass cannot produce panel PASS"])
        elif args.codex_handoff:
            if not args.worktree:
                raise ValueError("--worktree is required with --codex-handoff")
            handoff = json.loads(args.codex_handoff)
            panel = reviewer_plan.dispatch_codex_panel(plan, handoff, args.feature, args.worktree,
                                                       json.loads(args.referents),
                                                       baseline=args.baseline,
                                                       final_snapshot=args.final_snapshot)
        else:
            required_items = [p for p in plan if p.required]
            if len(raw_results) != len(required_items):
                raise ValueError("result collection is incomplete or contains extra results")
            results = []
            by_identity = {}
            for envelope in raw_results:
                if (not isinstance(envelope, dict) or not envelope.get("invocation_id")
                        or not isinstance(envelope.get("reviewer_id"), str)
                        or not isinstance(envelope.get("payload"), dict)):
                    raise ValueError("result collection lacks trusted Claude invocation identity")
                identity = envelope["reviewer_id"]
                if identity in by_identity:
                    raise ValueError("duplicate reviewer identity")
                by_identity[identity] = envelope
            if set(by_identity) != {item.reviewer_id for item in required_items}:
                raise ValueError("result collection contains an unexpected or missing reviewer")
            for item in required_items:
                results.append(reviewer_plan.normalize_reviewer_result(by_identity[item.reviewer_id]["payload"], item))
            panel = reviewer_plan.evaluate_panel_gate(plan, results)
        receipt, receipt_id, annotated = write_receipt(
            args.root, args.feature, args.phase, scope, panel, head, section=args.section
        )
        output = panel.to_dict()
        output["receipt"] = str(receipt) if receipt else None
        output["receipt_id"] = receipt_id
        output["annotated"] = annotated
        output["sha"] = head
        print(json.dumps(output, sort_keys=True))
        return 0 if panel.passed else 1
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"gate": "FAIL", "errors": [str(exc)]}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
