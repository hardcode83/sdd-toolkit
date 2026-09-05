from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sdd_lifecycle  # noqa: E402
import sdd_roadmap  # noqa: E402
from sdd_lifecycle import (  # noqa: E402
    LifecycleError,
    block_change,
    blocked_entries,
    ensure_local_gates,
    initial_state,
    mark_local_verified,
    write_state,
)
from validate_toolkit import run_doctor  # noqa: E402

FEATURE = "example"


class QueueFixture(unittest.TestCase):
    """A change whose tasks are all done, on its own branch, ready to certify."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.change = self.root / "sdd" / "changes" / FEATURE
        self.change.mkdir(parents=True)
        (self.root / "sdd" / "project.md").write_text("# Project\n", encoding="utf-8")
        (self.change / "proposal.md").write_text(
            "# Proposal\n\n## Requirements\n\n### R1 — Example\n", encoding="utf-8"
        )
        self.tasks("- [x] 1.1 Done [R1]\n")
        write_state(self.change, initial_state())
        self.git("init", "-q", "-b", "sdd/example")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "SDD Test")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "fixture")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        )

    def tasks(self, body: str) -> None:
        (self.change / "tasks.md").write_text("# Tasks\n\n## 1. Section\n\n" + body, encoding="utf-8")

    def blocked(self, text: str) -> None:
        (self.change / "BLOCKED.md").write_text(text, encoding="utf-8")

    def commit_all(self) -> None:
        self.git("add", ".")
        self.git("commit", "-q", "-m", "update")


class BlockedParsingTests(QueueFixture):
    """Months of hand-written BLOCKED.md files used several shapes; the parser
    reads all of them and fails closed on the ones it cannot read."""

    def test_canonical_and_legacy_shapes_are_read(self) -> None:
        self.blocked(
            "# BLOCKED — example\n\n"
            "## Secrets missing\n\n- **phase**: run\n- **type**: decision\n- **what & why**: x\n\n"
            "## Post-merge check\n\n- **Fase**: run\n- **Tipo**: `deferred` — el flujo puede reanudarlo\n\n"
            "## ops · run · decision — console sequence\n\nsome text\n\n"
            "## Entry 1 — DELETED — resolved earlier\n\nfix commit abc\n\n"
            "## Storage choice\n\n**Type:** assumed\nTook S3 (recommended). Tasks 2.3 and 2.4.\n"
        )
        entries = blocked_entries(self.change)
        self.assertEqual(
            ["decision", "deferred", "decision", "assumed"], [entry.kind for entry in entries]
        )
        self.assertEqual(("2.3", "2.4"), entries[3].tasks)
        self.assertTrue(entries[0].blocks_locally)
        self.assertFalse(entries[1].blocks_locally)
        self.assertFalse(entries[3].blocks_locally)

    def test_a_file_without_headings_is_one_entry(self) -> None:
        self.blocked("- phase: run · decision: ¿cuál?\n")
        entries = blocked_entries(self.change)
        self.assertEqual(1, len(entries))
        self.assertEqual("decision", entries[0].kind)

    def test_an_unreadable_type_is_unknown_and_blocks(self) -> None:
        self.blocked("## Something happened\n\nWe are not sure what to do.\n")
        (entry,) = blocked_entries(self.change)
        self.assertEqual("unknown", entry.kind)
        self.assertTrue(entry.blocks_locally)

    def test_two_different_type_words_without_a_type_line_are_unknown(self) -> None:
        self.blocked("## Mixed\n\nThis is deferred unless the decision changes.\n")
        (entry,) = blocked_entries(self.change)
        self.assertEqual("unknown", entry.kind)

    def test_empty_or_missing_file_has_no_entries(self) -> None:
        self.assertEqual([], blocked_entries(self.change))
        self.blocked("# BLOCKED\n\n")
        self.assertEqual([], blocked_entries(self.change))


class LocalGateTests(QueueFixture):
    """`decision` stops READY_FOR_PR; `deferred` and `assumed` travel with the PR."""

    def test_deferred_and_assumed_entries_do_not_block_certification(self) -> None:
        self.blocked(
            "## Post-merge verification\n\n- **type**: deferred\n- **exact resume command**: /sdd:run example 5\n\n"
            "## Took the recommended storage\n\n- **type**: assumed\n"
        )
        self.commit_all()
        ensure_local_gates(self.change)
        self.assertIn("LOCAL_VERIFIED", mark_local_verified(self.root, FEATURE))

    def test_a_decision_entry_still_blocks(self) -> None:
        self.blocked("## Secrets\n\n- **type**: decision\n")
        with self.assertRaisesRegex(LifecycleError, "unresolved work.*decision: Secrets"):
            ensure_local_gates(self.change)

    def test_an_unreadable_entry_fails_closed(self) -> None:
        self.blocked("## Something\n\nunclear\n")
        with self.assertRaisesRegex(LifecycleError, "unresolved work"):
            ensure_local_gates(self.change)

    def test_strict_gate_refuses_every_entry(self) -> None:
        """The archive is where the queue must be empty, whatever the type."""
        self.blocked("## Carried\n\n- **type**: assumed\n")
        ensure_local_gates(self.change)
        with self.assertRaisesRegex(LifecycleError, "unresolved work"):
            ensure_local_gates(self.change, strict=True)

    def test_a_manual_task_named_by_a_deferred_entry_may_stay_open(self) -> None:
        self.tasks(
            "- [x] 1.1 Done [R1]\n- [ ] 1.2 Manual browser check <!-- manual -->\n"
        )
        with self.assertRaisesRegex(LifecycleError, "incomplete task.*manual"):
            ensure_local_gates(self.change)
        self.blocked(
            "## Browser check needs a free port\n\n- **type**: deferred\n- **tasks**: 1.2\n"
        )
        ensure_local_gates(self.change)
        # The archive path still wants it done.
        with self.assertRaisesRegex(LifecycleError, "incomplete task.*archive requires"):
            ensure_local_gates(self.change, strict=True)

    def test_an_open_task_without_the_marker_blocks_even_if_deferred(self) -> None:
        self.tasks("- [x] 1.1 Done [R1]\n- [ ] 1.2 Not manual at all\n")
        self.blocked("## Whatever\n\n- **type**: deferred\n- **tasks**: 1.2\n")
        with self.assertRaisesRegex(LifecycleError, "incomplete task"):
            ensure_local_gates(self.change)


class BlockCommandTests(QueueFixture):
    def test_block_writes_a_canonical_entry_at_the_change_path(self) -> None:
        message = block_change(
            self.root,
            FEATURE,
            phase="review",
            kind="deferred",
            title="Manual browser check needs a free port",
            why="Host at 192MB free; make up PORT_OFFSET would destabilise peers.",
            resume="/sdd:run example 4.3",
            tasks=("4.3",),
        )
        self.assertIn("appended to sdd/changes/example/BLOCKED.md", message)
        text = (self.change / "BLOCKED.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# BLOCKED — example"))
        self.assertIn("## Manual browser check needs a free port", text)
        self.assertIn("- **type**: deferred", text)
        self.assertIn("- **tasks**: 4.3", text)
        (entry,) = blocked_entries(self.change)
        self.assertEqual(("deferred", ("4.3",)), (entry.kind, entry.tasks))
        # A second entry appends; the header is not repeated.
        block_change(
            self.root, FEATURE, phase="design", kind="assumed", title="Storage",
            why="S3, as recommended", resume="none",
        )
        self.assertEqual(1, (self.change / "BLOCKED.md").read_text(encoding="utf-8").count("# BLOCKED —"))
        self.assertEqual(2, len(blocked_entries(self.change)))

    def test_block_refuses_an_unknown_type_or_an_empty_field(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "Unknown BLOCKED type"):
            block_change(self.root, FEATURE, phase="run", kind="maybe", title="t", why="w", resume="r")
        with self.assertRaisesRegex(LifecycleError, "needs --title"):
            block_change(self.root, FEATURE, phase="run", kind="decision", title=" ", why="w", resume="r")

    def test_cli_block_and_blocked_round_trip(self) -> None:
        code = sdd_lifecycle.main([
            "--root", str(self.root), "block", FEATURE, "--phase", "run",
            "--type", "decision", "--title", "Secrets", "--why", "none in repo",
            "--resume", "/sdd:run example",
        ])
        self.assertEqual(0, code)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(0, sdd_lifecycle.main(["--root", str(self.root), "blocked", FEATURE, "--json"]))
        listed = json.loads(buffer.getvalue())
        self.assertEqual([("Secrets", "decision", True)], [(e["title"], e["type"], e["blocks_locally"]) for e in listed])


class RoadmapStatusTests(QueueFixture):
    def status(self) -> str:
        (self.root / "sdd" / "roadmap.md").write_text(
            "# Roadmap\n\n## Stage 1 — Example\n\n- [ ] example — algo\n", encoding="utf-8"
        )
        graph = sdd_roadmap.load(self.root)
        return graph.status[FEATURE]

    def test_only_a_decision_entry_shows_the_blocked_symbol(self) -> None:
        self.blocked("## Carried\n\n- **type**: deferred\n")
        self.assertEqual("ACTIVE", self.status())
        self.blocked("## Needs you\n\n- **type**: decision\n")
        self.assertEqual("BLOCKED", self.status())


class DoctorQueueTests(QueueFixture):
    def diagnose(self, code: str) -> list[str]:
        result = run_doctor(self.root)
        return [line for line in result.stdout.splitlines() if code in line]

    def test_an_unreadable_entry_is_reported_as_sdd030(self) -> None:
        self.blocked("## Something\n\nunclear\n")
        reported = self.diagnose("SDD030")
        self.assertEqual(1, len(reported), reported)
        self.assertIn("WARNING", reported[0])
        self.assertEqual([], self.diagnose("SDD031"))

    def test_an_uncovered_manual_task_is_reported_as_sdd031(self) -> None:
        self.tasks("- [x] 1.1 Done [R1]\n- [ ] 1.2 Browser pass <!-- manual -->\n")
        reported = self.diagnose("SDD031")
        self.assertEqual(1, len(reported), reported)
        self.assertIn("1.2", reported[0])
        self.blocked("## Browser\n\n- **type**: deferred\n- **tasks**: 1.2\n")
        self.assertEqual([], self.diagnose("SDD031"))
        self.assertEqual([], self.diagnose("SDD030"))


if __name__ == "__main__":
    unittest.main()
