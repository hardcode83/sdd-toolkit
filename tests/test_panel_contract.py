from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PANEL_AGENTS = ("sdd-architect", "sdd-security", "sdd-qa")


class PanelContractTests(unittest.TestCase):
    """The panel's two measured failure modes, pinned.

    Over 38 sessions of a real consumer project: 481 of 481 panel launches were
    sequential despite the skill asking for parallel, and the reviewers averaged
    60 tool-call turns each — rediscovering documents the caller already had.
    """

    def read_skill(self, name: str) -> str:
        return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")

    def read_agent(self, name: str) -> str:
        return (ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8")

    def test_the_panel_is_one_message_and_says_why(self) -> None:
        run = self.read_skill("run")
        self.assertIn("One message, every reviewer in it", run)
        self.assertIn("481 of 481", run)
        self.assertIn("2N round-trips", run)
        review = self.read_skill("review")
        self.assertIn("single**\n   assistant message", review)

    def test_reviewers_receive_their_referents_instead_of_hunting_for_them(self) -> None:
        run = self.read_skill("run")
        self.assertIn("referents inline", run)
        for quoted in ("with their EARS text", "**quoted**", "diff range"):
            self.assertIn(quoted, run)

    def test_every_panel_agent_has_a_turn_budget(self) -> None:
        for agent in PANEL_AGENTS:
            with self.subTest(agent=agent):
                text = self.read_agent(agent)
                self.assertIn("## Budget:", text)
                self.assertIn("tool calls", text)
                # A budget that drops the findings is worse than no budget.
                self.assertIn("what you could not reach", text)

    def test_agents_skip_referents_the_prompt_already_carries(self) -> None:
        for agent in PANEL_AGENTS:
            with self.subTest(agent=agent):
                self.assertIn(
                    "skip any the prompt already quotes", self.read_agent(agent)
                )

    def test_the_referent_filter_survives_all_of_this(self) -> None:
        """The panel's best property: no referent, no finding."""
        for agent in PANEL_AGENTS:
            with self.subTest(agent=agent):
                text = self.read_agent(agent)
                self.assertIn("referent", text)
                self.assertIn("PASS", text)


if __name__ == "__main__":
    unittest.main()
