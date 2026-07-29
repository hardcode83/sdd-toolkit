from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LifecycleSkillContractTests(unittest.TestCase):
    def read_skill(self, name: str) -> str:
        return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")

    def test_auto_stops_after_recording_pr(self) -> None:
        auto = self.read_skill("auto")
        self.assertIn("**STOP before archive.**", auto)
        self.assertIn("record-pr <feature>", auto)
        self.assertNotIn("**archive** — follow the archive skill", auto)
        self.assertIn("Do not call `/sdd:archive`", auto)
        self.assertIn("Re-running is", auto)
        self.assertIn("No remote or no `gh` → leave `READY_FOR_PR`", auto)

    def test_archive_checks_merge_before_specs(self) -> None:
        archive = self.read_skill("archive")
        gate = archive.index("verify-merge <feature>")
        specs = archive.index("Update the living specs only now")
        finalize = archive.index("finalize-archive <feature>")
        self.assertLess(gate, specs)
        self.assertLess(specs, finalize)
        self.assertIn("has no override", archive)

    def test_review_persists_ready_for_pr(self) -> None:
        review = self.read_skill("review")
        self.assertIn("mark-local-verified <feature>", review)
        self.assertIn("mark-ready <feature>", review)
        self.assertIn("state: READY_FOR_PR", review)

    def test_new_initializes_active_lifecycle(self) -> None:
        new = self.read_skill("new")
        self.assertIn("start <feature>", new)
        self.assertIn("state: ACTIVE", new)

    def test_status_exposes_every_non_archived_state(self) -> None:
        status = self.read_skill("status")
        for state in (
            "ACTIVE",
            "LOCAL_VERIFIED",
            "READY_FOR_PR",
            "PR_OPEN",
            "MERGED",
            "CANCELLED",
        ):
            self.assertIn(state, status)
        self.assertIn("BLOCKED.md", status)


if __name__ == "__main__":
    unittest.main()
