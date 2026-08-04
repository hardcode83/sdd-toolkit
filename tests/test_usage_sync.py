from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util  # noqa: E402


def load_module():
    """usage-sync.py is not an importable name, so load it by path."""
    spec = importlib.util.spec_from_file_location(
        "usage_sync", ROOT / "scripts" / "usage-sync.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


usage_sync = load_module()
FEATURE = "example"
# 2026-07-24 12:00 local-independent enough for a date assertion via the module.
STAMP = 1_780_000_000


class UsageSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.change = self.root / "sdd" / "changes" / FEATURE
        self.change.mkdir(parents=True)
        (self.root / ".sdd-usage").mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_log(self, *rows: dict) -> None:
        path = self.root / ".sdd-usage" / "otel.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def datapoint(
        self,
        phase: str,
        *,
        metric: str = "tokens",
        kind: str = "input",
        value: float = 100,
        source: str = "main",
        model: str = "claude-opus-5",
        ts: int = STAMP,
    ) -> dict:
        return {
            "ts": ts,
            "metric": metric,
            "type": kind if metric == "tokens" else None,
            "model": model,
            "session": "s1",
            "source": source,
            "value": value,
            "task": f"{FEATURE}/{phase}",
        }

    def phase_usage(self, phase: str, *, cost: float, ts: int = STAMP) -> None:
        self.write_log(
            self.datapoint(phase, kind="input", value=10, ts=ts),
            self.datapoint(phase, kind="output", value=200, ts=ts),
            self.datapoint(phase, kind="cacheRead", value=5000, ts=ts),
            self.datapoint(phase, metric="cost", value=cost, ts=ts),
        )

    def ledger(self) -> str:
        return (self.change / "metrics.md").read_text(encoding="utf-8")

    def summary(self) -> str:
        return (self.root / "sdd" / "metrics.md").read_text(encoding="utf-8")

    def test_sync_writes_every_captured_phase_and_consolidates(self) -> None:
        self.phase_usage("new", cost=1.5, ts=STAMP)
        self.phase_usage("run", cost=40.25, ts=STAMP + 3600)
        self.assertEqual(0, usage_sync.sync(self.root, FEATURE))
        ledger = self.ledger()
        self.assertIn("| new |", ledger)
        self.assertIn("| run |", ledger)
        self.assertIn("41.7500", self.summary())
        self.assertIn("| new, run |", self.summary())
        # Not archived yet: the loop is explicitly still open.
        self.assertIn("| — |\n", self.summary())

    def test_sync_recovers_a_phase_the_gate_never_wrote(self) -> None:
        """The exact failure mode: captured spend with no ledger row."""
        (self.change / "metrics.md").write_text(
            f"# Metrics: {FEATURE}\n\n{usage_sync.LEDGER_HEADER}"
            "| 2026-07-22 | new | claude-opus-5 | 7 | 4350 | 1166814 | 0.7687 |  |\n",
            encoding="utf-8",
        )
        self.phase_usage("new", cost=0.7687)
        self.phase_usage("run", cost=39.44, ts=STAMP + 60)
        usage_sync.sync(self.root, FEATURE)
        self.assertIn("39.4400", self.ledger())
        self.assertIn("| run |", self.ledger())

    def test_sync_is_idempotent(self) -> None:
        self.phase_usage("design", cost=5.85)
        usage_sync.sync(self.root, FEATURE)
        first = (self.ledger(), self.summary())
        usage_sync.sync(self.root, FEATURE)
        self.assertEqual(first, (self.ledger(), self.summary()))

    def test_sync_never_lowers_a_row_the_log_cannot_explain(self) -> None:
        (self.change / "metrics.md").write_text(
            f"# Metrics: {FEATURE}\n\n{usage_sync.LEDGER_HEADER}"
            "| 2026-07-18 | run | claude-opus-5 | 19001 | 401889 | 61077281 | 58.4514 |  |\n",
            encoding="utf-8",
        )
        self.phase_usage("run", cost=15.07)
        usage_sync.sync(self.root, FEATURE)
        self.assertIn("58.4514", self.ledger())
        self.assertNotIn("15.0700", self.ledger())

    def test_sub_cent_rounding_is_not_treated_as_lost_data(self) -> None:
        """Ledger rows carry four decimals; that rounding must not raise a warning."""
        (self.change / "metrics.md").write_text(
            f"# Metrics: {FEATURE}\n\n{usage_sync.LEDGER_HEADER}"
            "| 2026-07-17 | tasks | claude-opus-5 | 5 | 90 | 1000 | 0.7739 |  |\n",
            encoding="utf-8",
        )
        self.phase_usage("tasks", cost=0.77385)
        totals = usage_sync.totals_by_feature(usage_sync.load_log(self.root))[FEATURE]
        _, warnings = usage_sync.sync_ledger(self.change, FEATURE, totals)
        self.assertEqual([], warnings)
        self.assertIn("0.7739", self.ledger())

    def test_sync_keeps_phases_absent_from_the_log(self) -> None:
        (self.change / "metrics.md").write_text(
            f"# Metrics: {FEATURE}\n\n{usage_sync.LEDGER_HEADER}"
            "| 2026-07-01 | tasks | claude-opus-4-8 | 5 | 90 | 1000 | 0.5000 |  |\n",
            encoding="utf-8",
        )
        self.phase_usage("run", cost=2.0)
        usage_sync.sync(self.root, FEATURE)
        self.assertIn("| tasks |", self.ledger())
        self.assertIn("| run |", self.ledger())

    def test_sync_repairs_an_archived_change_and_dates_it(self) -> None:
        archived = self.root / "sdd" / "changes" / "archive" / f"2026-07-24-{FEATURE}"
        archived.mkdir(parents=True)
        self.change.rmdir()
        self.phase_usage("archive", cost=22.82)
        usage_sync.sync(self.root, FEATURE)
        self.assertIn("22.8200", (archived / "metrics.md").read_text(encoding="utf-8"))
        self.assertIn("| 2026-07-24 |\n", self.summary())

    def test_untagged_spend_is_never_attributed_to_a_phase(self) -> None:
        row = self.datapoint("run", metric="cost", value=9.99)
        row["task"] = ""
        self.write_log(row)
        self.phase_usage("run", cost=1.0)
        usage_sync.sync(self.root, FEATURE)
        self.assertIn("1.0000", self.ledger())
        self.assertNotIn("9.99", self.ledger())

    def test_report_names_the_features_that_need_syncing(self) -> None:
        self.phase_usage("run", cost=39.44)
        self.assertEqual(0, usage_sync.report(self.root))

    def test_missing_log_is_a_silent_no_op(self) -> None:
        (self.root / ".sdd-usage" / "otel.jsonl").unlink(missing_ok=True)
        self.assertEqual(0, usage_sync.sync(self.root, FEATURE))
        self.assertFalse((self.change / "metrics.md").exists())

    def test_unknown_feature_is_an_actionable_error(self) -> None:
        self.phase_usage("run", cost=1.0)
        with self.assertRaises(usage_sync.UsageError):
            usage_sync.sync(self.root, "not-a-change")


def load_sink():
    """usage-sink.py is not an importable name either."""
    spec = importlib.util.spec_from_file_location(
        "usage_sink", ROOT / "scripts" / "usage-sink.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SharedUsageDirTests(unittest.TestCase):
    """One sink, one log for the whole repository — worktrees included."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "SDD Test")
        (self.root / "seed.txt").write_text("seed\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")

    def git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        )

    def test_a_worktree_resolves_to_the_main_worktrees_log(self) -> None:
        linked = self.root / ".claude" / "worktrees" / "alpha"
        self.git("worktree", "add", "-b", "sdd/alpha", str(linked))
        self.assertEqual(
            self.root / ".sdd-usage", usage_sync.usage_dir(self.root)
        )
        self.assertEqual(
            self.root / ".sdd-usage", usage_sync.usage_dir(linked)
        )

    def test_outside_a_repository_it_degrades_to_the_given_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plain = Path(directory).resolve()
            self.assertEqual(plain / ".sdd-usage", usage_sync.usage_dir(plain))


class SinkAttributionTests(unittest.TestCase):
    """Attribution is per session: a shared pointer was last-writer-wins."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.usage = Path(self.temporary.name) / ".sdd-usage"
        (self.usage / "tasks").mkdir(parents=True)
        previous = os.environ.get("SDD_USAGE_DIR")
        os.environ["SDD_USAGE_DIR"] = str(self.usage)
        self.addCleanup(self._restore, previous)
        self.sink = load_sink()

    @staticmethod
    def _restore(previous: str | None) -> None:
        if previous is None:
            os.environ.pop("SDD_USAGE_DIR", None)
        else:
            os.environ["SDD_USAGE_DIR"] = previous

    def mark(self, session: str, task: str) -> None:
        (self.usage / "tasks" / session).write_text(task, encoding="utf-8")

    def test_each_session_is_attributed_to_its_own_feature(self) -> None:
        self.mark("session-a", "alpha/run")
        self.mark("session-b", "beta/design")
        cache: dict[str, str] = {}
        self.assertEqual("alpha/run", self.sink.task_for("session-a", cache))
        self.assertEqual("beta/design", self.sink.task_for("session-b", cache))

    def test_an_unknown_session_falls_back_to_the_shared_pointer(self) -> None:
        (self.usage / "current-task").write_text("alpha/run", encoding="utf-8")
        cache: dict[str, str] = {}
        self.assertEqual("alpha/run", self.sink.task_for(None, cache))
        self.assertEqual("alpha/run", self.sink.task_for("never-marked", cache))

    def test_nothing_marked_at_all_attributes_to_nothing(self) -> None:
        self.assertEqual("", self.sink.task_for("session-a", {}))

    def test_the_cache_reads_each_session_once(self) -> None:
        self.mark("session-a", "alpha/run")
        cache: dict[str, str] = {}
        self.assertEqual("alpha/run", self.sink.task_for("session-a", cache))
        self.mark("session-a", "alpha/review")
        self.assertEqual("alpha/run", self.sink.task_for("session-a", cache))


if __name__ == "__main__":
    unittest.main()
