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
from sdd_lifecycle import initial_state, preflight_archive, read_state, write_state  # noqa: E402

FEATURE = "example"


class PreflightFixture(unittest.TestCase):
    """A change merged into main by a local merge (the `ancestor` evidence path),
    so the archive preconditions can be met without GitHub."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.change = self.root / "sdd" / "changes" / FEATURE
        self.change.mkdir(parents=True)
        (self.root / "sdd" / "project.md").write_text("# Project\n", encoding="utf-8")
        (self.root / "sdd" / "roadmap.md").write_text(
            "# Roadmap\n\n## Stage 1 — Example\n\n- [ ] example — algo\n", encoding="utf-8"
        )
        (self.change / "proposal.md").write_text("# Proposal\n\n## Requirements\n\n### R1 — Example\n", encoding="utf-8")
        (self.change / "tasks.md").write_text("# Tasks\n\n- [x] 1.1 Done [R1]\n", encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "SDD Test")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "base")
        # Feature work on its branch, then merged back into main.
        self.git("switch", "-q", "-c", f"sdd/{FEATURE}")
        (self.root / "feature.txt").write_text("done\n", encoding="utf-8")
        write_state(self.change, initial_state())
        self.git("add", ".")
        self.git("commit", "-q", "-m", "feature work")
        self.implementation_sha = self.head()
        state = read_state(self.change)
        state.update({
            "state": "READY_FOR_PR", "local_review": "APPROVED", "base_branch": "main",
            "head_branch": f"sdd/{FEATURE}", "implementation_sha": self.implementation_sha,
        })
        write_state(self.change, state)
        self.git("add", ".")
        self.git("commit", "-q", "-m", "chore(sdd): lifecycle example ACTIVE->READY_FOR_PR")
        self.git("switch", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", "merge feature", f"sdd/{FEATURE}")

    def git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=cwd or self.root, check=True, capture_output=True, text=True)

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def failed(self, report: dict) -> dict[str, str]:
        return {c["check"]: c["fix"] for c in report["checks"] if not c["ok"]}


class PreflightTests(PreflightFixture):
    def test_a_merged_change_on_a_clean_base_is_ready(self) -> None:
        report = preflight_archive(self.root, FEATURE, fetch=False)
        self.assertTrue(report["ready"], report)
        self.assertEqual("main", report["base"])
        names = [c["check"] for c in report["checks"]]
        for expected in ("main-worktree", "change-present", "base-branch", "clean-tree",
                         "remote-integrated", "tasks-and-queue", "local-review", "merge-evidence", "roadmap-entry"):
            self.assertIn(expected, names)
        # Nothing was written: STATE.md still says READY_FOR_PR on disk.
        self.assertEqual("READY_FOR_PR", read_state(self.change)["state"])

    def test_every_failing_precondition_is_reported_at_once_with_its_fix(self) -> None:
        self.git("switch", "-q", "-c", "other")
        (self.root / "dirty.txt").write_text("x\n", encoding="utf-8")
        (self.change / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 Not done [R1]\n", encoding="utf-8")
        report = preflight_archive(self.root, FEATURE, base="main", fetch=False)
        self.assertFalse(report["ready"])
        failed = self.failed(report)
        self.assertIn("git switch main", failed["base-branch"])
        self.assertIn("Commit or stash", failed["clean-tree"])
        self.assertIn("Finish or record the tasks", failed["tasks-and-queue"])
        self.assertGreaterEqual(len(failed), 3, "all failures in one pass, not one per run")

    def test_a_linked_worktree_names_the_main_one(self) -> None:
        linked = self.root / ".claude" / "worktrees" / "arch"
        self.git("worktree", "add", "-q", "--detach", str(linked))
        report = preflight_archive(linked, FEATURE, base="main", fetch=False)
        failed = self.failed(report)
        self.assertIn(f"cd {self.root}", failed["main-worktree"])

    def test_a_missing_change_points_at_the_pull(self) -> None:
        report = preflight_archive(self.root, "ghost", base="main", fetch=False)
        self.assertIn("git pull --ff-only origin", self.failed(report)["change-present"])

    def test_an_already_archived_change_is_named_as_such(self) -> None:
        archive = self.root / "sdd" / "changes" / "archive" / f"2026-09-01-{FEATURE}"
        archive.mkdir(parents=True)
        (archive / "proposal.md").write_text("# P\n", encoding="utf-8")
        import shutil
        shutil.rmtree(self.change)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "archived")
        report = preflight_archive(self.root, FEATURE, base="main", fetch=False)
        self.assertIn("already archived", next(c["detail"] for c in report["checks"] if c["check"] == "change-present"))

    def test_an_unmerged_change_fails_on_evidence_not_on_the_tree(self) -> None:
        # Undo the merge: main no longer contains the reviewed commit.
        self.git("reset", "-q", "--hard", "HEAD~1")
        # The change directory only exists on the feature branch now; bring the docs back on main
        self.git("checkout", "-q", f"sdd/{FEATURE}", "--", "sdd/changes/example")
        self.git("commit", "-q", "-m", "docs only")
        report = preflight_archive(self.root, FEATURE, base="main", fetch=False)
        failed = self.failed(report)
        self.assertIn("merge-evidence", failed)
        self.assertNotIn("clean-tree", failed)

    def test_a_missing_roadmap_entry_is_reported(self) -> None:
        (self.root / "sdd" / "roadmap.md").write_text("# Roadmap\n\n- [ ] other — algo\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "roadmap")
        report = preflight_archive(self.root, FEATURE, base="main", fetch=False)
        self.assertIn("roadmap-entry", self.failed(report))

    def test_cli_last_line_and_exit_code(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sdd_lifecycle.main(["--root", str(self.root), "preflight-archive", FEATURE, "--no-fetch"])
        self.assertEqual(0, code)
        self.assertEqual("PREFLIGHT: READY", buffer.getvalue().strip().splitlines()[-1])
        (self.root / "dirty.txt").write_text("x\n", encoding="utf-8")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sdd_lifecycle.main(["--root", str(self.root), "preflight-archive", FEATURE, "--no-fetch", "--json"])
        self.assertEqual(2, code)
        self.assertFalse(json.loads(buffer.getvalue())["ready"])


if __name__ == "__main__":
    unittest.main()
