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
        self.assertIn("leave `READY_FOR_PR`", auto)
        self.assertIn("Never fabricate a URL", auto)

    def test_auto_never_asks_for_the_base_branch(self) -> None:
        """The base is a precondition of the run, not a question mid-flight."""
        auto = self.read_skill("auto")
        self.assertIn("mark-ready <feature> --base <BASE>", auto)
        self.assertIn("mark-local-verified <feature>", auto)
        review = self.read_skill("review")
        self.assertIn("except under `/sdd:auto`", review)

    def test_auto_never_interrupts_the_run_with_a_question(self) -> None:
        """An unattended run must convert every question, not raise it."""
        auto = self.read_skill("auto")
        self.assertIn("**Auto never asks the user anything.**", auto)
        self.assertIn("Do not call `AskUserQuestion`", auto)
        # Each question point found in the phase skills has a stated substitute.
        for substituted in (
            "Shared rule 6",
            "Missing arguments",
            "Ad-hoc roadmap registration",
            "stop and ask",
        ):
            self.assertIn(substituted, auto)
        self.assertIn("do not ask for confirmation", auto)

    def test_auto_treats_human_only_steps_as_handoffs(self) -> None:
        auto = self.read_skill("auto")
        self.assertIn("Handoff: the steps that stay the user's", auto)
        self.assertIn("handoffs, not failures", auto)
        self.assertIn("yours to run", auto)
        self.assertIn("never stops the run", auto)

    def test_auto_distinguishes_own_change_from_a_foreign_claim(self) -> None:
        auto = self.read_skill("auto")
        self.assertIn("our own in-flight\n     change", auto)
        self.assertIn("no local change directory", auto)

    def test_archive_accepts_history_rewriting_merges(self) -> None:
        archive = self.read_skill("archive")
        self.assertIn("merge_evidence: equivalent", archive)
        self.assertIn("squash and rebase merges", archive)

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
