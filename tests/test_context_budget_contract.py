from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContextBudgetContractTests(unittest.TestCase):
    """Cost follows position in the session, not the work a phase does.

    Measured over 38 sessions of a real consumer project: `review` averaged 571k
    of context per request and `archive` 634k, while new/design/tasks together
    were 6.6% of all spend. The terminal phases are expensive because they run
    last — so they must not inherit what came before.
    """

    def read_skill(self, name: str) -> str:
        return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")

    def test_the_rule_is_stated_once_and_backed_by_the_measurement(self) -> None:
        rules = (ROOT / "rules.md").read_text(encoding="utf-8")
        self.assertIn("A phase does not inherit the previous phase's context", rules)
        self.assertIn("references/context-budget.md", rules)
        self.assertTrue((ROOT / "references" / "context-budget.md").exists())

    def test_terminal_phases_recommend_a_fresh_context(self) -> None:
        for phase in ("review", "archive"):
            with self.subTest(phase=phase):
                self.assertIn("shared rule 11", self.read_skill(phase))
        # And the phase that fills the context says so where it hands over.
        self.assertIn("Recommend `/clear` first", self.read_skill("run"))

    def test_the_advice_is_never_a_gate(self) -> None:
        """A cost optimisation that can block a phase is worse than the cost."""
        self.assertIn("this is advice, not\n   a gate", self.read_skill("review"))

    def test_auto_delegates_instead_of_accumulating(self) -> None:
        auto = self.read_skill("auto")
        self.assertIn("claude -p", auto)
        self.assertIn("SDD_AUTO_DELEGATED", auto)
        self.assertIn("never aborts a run", auto)

    def test_a_delegated_run_cannot_delegate_again(self) -> None:
        auto = self.read_skill("auto")
        self.assertIn("you *are* the\n  delegated run", auto)

    def test_delegated_outcomes_are_read_from_disk_not_from_prose(self) -> None:
        """Same reason the merge gate reads git and GitHub: a summary is a claim,
        STATE.md is a fact."""
        auto = self.read_skill("auto")
        self.assertIn("Read the outcome from disk", auto)
        self.assertIn("read the result from disk, not from the prose", auto)
        budget = (ROOT / "references" / "context-budget.md").read_text(encoding="utf-8")
        self.assertIn("Reading the result, not the prose", budget)

    def test_delegation_does_not_lose_the_metrics(self) -> None:
        budget = (ROOT / "references" / "context-budget.md").read_text(encoding="utf-8")
        self.assertIn("one sink per repository", budget)
        self.assertIn("references/metrics.md", self.read_skill("auto"))


if __name__ == "__main__":
    unittest.main()
