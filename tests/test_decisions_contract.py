from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(*parts: str) -> str:
    return (ROOT / Path(*parts)).read_text(encoding="utf-8")


class ThreeLevelQueueContractTests(unittest.TestCase):
    """ADR 0006: the pending queue has three types and the gates read them."""

    def test_rule_5_names_the_three_types_and_the_generic_authorisation_rule(self) -> None:
        rules = read("rules.md")
        for phrase in ("`decision`", "`deferred`", "`assumed`", "block <feature>",
                       "never write the\n     user's name", "0006-decisions-three-levels"):
            self.assertIn(phrase, rules)

    def test_rule_11_says_a_fork_waits_in_the_foreground(self) -> None:
        rules = read("rules.md")
        self.assertIn("A fork waits in the foreground", rules)
        self.assertIn("Ending the turn ends the fork", rules)

    def test_skills_write_blocked_entries_with_the_script_not_by_hand(self) -> None:
        for skill in ("auto", "run", "review"):
            with self.subTest(skill=skill):
                text = read("skills", skill, "SKILL.md")
                self.assertIn("block", text)
                self.assertIn("sdd_lifecycle.py", text)
        self.assertIn("never by hand", read("skills", "auto", "SKILL.md"))
        self.assertIn("never write `BLOCKED.md` by hand", read("skills", "review", "SKILL.md"))

    def test_auto_records_assumed_choices_and_generic_authorisations(self) -> None:
        auto = read("skills", "auto", "SKILL.md")
        self.assertIn("record an `assumed` entry", auto)
        self.assertIn("A generic authorisation from the human", auto)
        self.assertIn("never write the user's name on a choice they did not make", auto)
        self.assertIn("`<!-- manual -->` tasks", auto)

    def test_manual_tasks_are_marked_in_tasks_and_left_to_the_human(self) -> None:
        self.assertIn("<!-- manual -->", read("templates", "tasks-template.md"))
        self.assertIn("Mark the manual tasks", read("skills", "tasks", "SKILL.md"))
        run = read("skills", "run", "SKILL.md")
        self.assertIn("leave them unchecked and untouched", run)
        self.assertIn("--type deferred", run)
        self.assertIn("An open `<!-- manual -->` task is not a FAIL", read("skills", "review", "SKILL.md"))

    def test_status_ship_and_archive_agree_on_what_travels_with_the_pr(self) -> None:
        self.assertIn("`assumed`", read("skills", "status", "SKILL.md"))
        ship = read("skills", "ship", "SKILL.md")
        self.assertIn("do **not** stop ship", ship)
        self.assertIn("Pending, travelling with this PR", ship)
        self.assertIn("no `BLOCKED.md` entry of any\n   type", read("skills", "archive", "SKILL.md"))


class FixLadderContractTests(unittest.TestCase):
    def test_run_climbs_sonnet_then_opus_then_hands_both_positions_to_the_user(self) -> None:
        run = read("skills", "run", "SKILL.md")
        self.assertIn("**Round 1**: implementer on `model: sonnet`", run)
        self.assertIn("**Round 2**: implementer on `model: opus`", run)
        self.assertIn("round-1 implementer's report", run)
        self.assertIn("*Persistence*", run)
        self.assertIn("*Churn*", run)
        self.assertIn("The panel gate is unchanged", run)

    def test_every_agent_call_names_an_alias_never_a_model_id(self) -> None:
        run = read("skills", "run", "SKILL.md")
        self.assertIn("Every `Agent` call carries `model:`", run)
        self.assertIn("references/models.md", run)
        self.assertIn("Aliases, never model IDs", run)
        models = read("references", "models.md")
        for alias in ("`haiku`", "`sonnet`", "`opus`", "`fable`"):
            self.assertIn(alias, models)
        self.assertIn("ANTHROPIC_DEFAULT_SONNET_MODEL", models)
        # No concrete Anthropic model ID anywhere a consumer executes.
        for path in (ROOT / "skills").rglob("SKILL.md"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"claude-(opus|sonnet|haiku|fable)-\d")
        for path in (ROOT / "agents").glob("*.md"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"claude-(opus|sonnet|haiku|fable)-\d")


class ReviewFixLadderContractTests(unittest.TestCase):
    """Measured: 52 of 84 features needed more than one review; auto used to BLOCK
    on the first FAIL without trying a fix."""

    def test_auto_climbs_the_ladder_on_a_failed_review(self) -> None:
        auto = read("skills", "auto", "SKILL.md")
        self.assertIn("`FAILED` is not a block yet", auto)
        self.assertIn("review fixes — round 1", auto)
        self.assertIn("`model: opus`, given the\n      new findings", auto)
        self.assertIn("re-run the delegated\n      review", auto)
        self.assertIn("Two rounds is the cap", auto)

    def test_review_fills_findings_for_the_caller_under_auto(self) -> None:
        review = read("skills", "review", "SKILL.md")
        self.assertIn("fill the outcome object's `findings`", review)
        self.assertIn("auto runs the fix\n   ladder", review)


class ForegroundForkContractTests(unittest.TestCase):
    def test_review_and_the_panel_wait_in_the_foreground(self) -> None:
        self.assertIn("In the foreground, and wait in this turn", read("skills", "review", "SKILL.md"))
        self.assertIn("in the foreground", read("skills", "reviewer-panel", "SKILL.md"))


if __name__ == "__main__":
    unittest.main()
