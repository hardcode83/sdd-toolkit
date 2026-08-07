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
        self.assertIn("record-pr", auto)
        self.assertNotIn("**archive** — follow the archive skill", auto)
        self.assertIn("Do not call `/sdd:archive`", auto)
        self.assertIn("leave `READY_FOR_PR`", auto)
        self.assertIn("Never fabricate a URL", auto)

    def test_publishing_has_one_home_and_auto_delegates_to_it(self) -> None:
        """Two copies of a publishing contract drift; the PR evidence is the one
        fact the merge gate later depends on, so it gets a single owner."""
        ship = self.read_skill("ship")
        self.assertIn("record-pr <feature> --url <PR-URL>", ship)
        self.assertIn("Re-running is idempotent", ship)
        self.assertIn("Never fabricate a URL", ship)
        self.assertIn("leave the change at `READY_FOR_PR`", ship)
        # Ship publishes and nothing else: no review, no merge, no archive.
        self.assertIn("never merges and never archives", ship)
        self.assertIn("/sdd:archive <feature>", ship)
        # Auto reaches it by reference, not by copy.
        auto = self.read_skill("auto")
        self.assertIn("skills/ship/SKILL.md", auto)
        self.assertNotIn("gh pr create", auto.split("## Final report")[0])

    def test_ship_refuses_to_publish_an_unreviewed_range(self) -> None:
        """mark-ready recorded the SHA the verdict covers; if HEAD moved past it,
        the PR would carry an approved verdict over unreviewed commits."""
        ship = self.read_skill("ship")
        self.assertIn("implementation_sha", ship)
        self.assertIn("`/sdd:review <feature>`", ship)
        self.assertIn("Never ask for the base branch", ship)

    def test_review_offers_to_publish_but_stays_report_only(self) -> None:
        review = self.read_skill("review")
        self.assertIn("skills/ship/SKILL.md", review)
        self.assertIn("remains\nreport-only", review)
        self.assertIn("Skip this question entirely under `/sdd:auto`", review)

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

    def test_archive_commits_what_it_moved_instead_of_suggesting_it(self) -> None:
        """finalize-archive stages the move and leaves specs/roadmap/metrics
        unstaged; stopping there is how a half-committed archive — an orphaned
        STATE.md on the base branch — reaches somebody else's run."""
        archive = self.read_skill("archive")
        self.assertIn("git add -A sdd/", archive)
        self.assertIn("Commit the archive?", archive)
        self.assertNotIn("Suggest committing", archive)
        # One closing question, not one turn per decision.
        self.assertIn("both questions in the same call", archive)
        self.assertIn("Never pass `--force` on the user's behalf", archive)

    def test_review_persists_ready_for_pr(self) -> None:
        review = self.read_skill("review")
        self.assertIn("mark-local-verified <feature>", review)
        self.assertIn("mark-ready <feature>", review)
        self.assertIn("state: READY_FOR_PR", review)

    def test_new_initializes_active_lifecycle(self) -> None:
        new = self.read_skill("new")
        self.assertIn("start <feature>", new)
        self.assertIn("state: ACTIVE", new)

    def test_every_phase_skill_records_its_own_usage(self) -> None:
        """An uninstrumented phase does not lose its spend — it misattributes it
        to whichever phase marked itself last, silently."""
        for phase in ("new", "design", "tasks", "run", "review", "ship", "archive"):
            skill = self.read_skill(phase)
            with self.subTest(phase=phase):
                self.assertIn(f'usage-mark.sh" {phase}', skill.replace("<feature> ", ""))
                self.assertIn(f'usage-phase.sh" {phase}', skill.replace("<feature> ", ""))

    def test_metrics_are_consolidated_from_the_log_not_by_hand(self) -> None:
        archive = self.read_skill("archive")
        self.assertIn("usage-sync.py", archive)
        self.assertIn("Do **not** consolidate by hand", archive)
        # After the move, so the archive date and the phase's tail are included.
        self.assertLess(archive.index("finalize-archive <feature>"), archive.index("usage-sync.py"))
        self.assertIn("usage-sync.py", self.read_skill("review"))

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
