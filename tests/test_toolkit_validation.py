from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_toolkit import (  # noqa: E402
    STACK_COMMAND_RE,
    parse_frontmatter,
    release_guard_errors,
    validate_codex_manifests,
    validate_manifests,
    validate_project_boundary,
    validate_reviewer_panel,
    validate_skills,
)


class ToolkitStructureTests(unittest.TestCase):
    def test_manifests_are_valid(self) -> None:
        self.assertEqual([], validate_manifests())

    def test_skills_are_valid_and_references_resolve(self) -> None:
        self.assertEqual([], validate_skills())

    def test_plugin_and_consumer_assets_have_an_explicit_boundary(self) -> None:
        self.assertEqual([], validate_project_boundary())

    def test_claude_adapters_match_canonical_registry(self) -> None:
        self.assertEqual([], validate_reviewer_panel())

    def test_codex_adapter_version_must_track_the_plugin_it_adapts(self) -> None:
        """The adapter exposes these skills, so it cannot announce another release."""
        errors = validate_codex_manifests(ROOT, "9.9.9")
        self.assertTrue(any("must match" in error for error in errors), errors)

    def test_frontend_steering_template_has_frontmatter_and_no_stack_command(
        self,
    ) -> None:
        """The UI/UX lens needs a citable, stack-agnostic steering baseline."""
        path = ROOT / "templates" / "steering" / "frontend.md"
        errors: list[str] = []
        data = parse_frontmatter(path, ROOT, errors)
        self.assertEqual([], errors)
        self.assertIn("applies_to", data)
        content = path.read_text(encoding="utf-8")
        self.assertIsNone(STACK_COMMAND_RE.search(content))

    def test_ui_ux_reviewer_template_has_valid_frontmatter(self) -> None:
        """The specialized UI/UX reviewer template must pass the same
        frontmatter contract as every other reviewer/skill artifact, and
        must ship phases/applies_to already filled so a generated agent
        does not trip SDD028."""
        path = ROOT / "templates" / "reviewer-ui-ux.md"
        errors: list[str] = []
        data = parse_frontmatter(path, ROOT, errors)
        self.assertEqual([], errors)
        self.assertEqual("sdd-review-ui-ux", data.get("name"))
        self.assertTrue(data.get("description"))
        self.assertTrue(data.get("model"))
        self.assertTrue(data.get("tools"))
        self.assertIn("phases", data)
        self.assertIn("applies_to", data)


class ReleaseGuardTests(unittest.TestCase):
    """A change to distributed behaviour must declare a new version.

    Merging one without it publishes to nobody: the installer only offers an
    update when `version` changes. It happened twice before this check existed.
    """

    def guard(self, changed: list[str], bumped: bool = False) -> list[str]:
        return release_guard_errors(changed, bumped)

    def test_distributed_change_without_a_bump_fails(self) -> None:
        for path in (
            "skills/run/SKILL.md",
            "scripts/sdd_roadmap.py",
            "agents/sdd-qa.md",
            "templates/roadmap-template.md",
            "references/isolation.md",
            "hooks/hooks.json",
            "rules.md",
        ):
            with self.subTest(path=path):
                self.assertEqual(1, len(self.guard([path])))

    def test_the_same_change_passes_once_the_version_moves(self) -> None:
        self.assertEqual([], self.guard(["skills/run/SKILL.md"], bumped=True))

    def test_docs_and_tests_never_require_a_bump(self) -> None:
        self.assertEqual(
            [],
            self.guard(
                [
                    "README.md",
                    "docs/guide.md",
                    "docs/adr/0001-roadmap-structure-and-concurrency.md",
                    "tests/test_sdd_roadmap.py",
                    "tests/fixtures/valid/sdd/project.md",
                    ".github/workflows/validate-toolkit.yml",
                ]
            ),
        )

    def test_the_repos_own_ci_tooling_is_exempt(self) -> None:
        """Copied to consumers but never run by them, like the fixtures."""
        self.assertEqual([], self.guard(["scripts/validate_toolkit.py"]))
        self.assertEqual(1, len(self.guard(["scripts/sdd-doctor.py"])))

    def test_the_message_names_the_files_and_both_manifests(self) -> None:
        message = self.guard(["skills/new/SKILL.md", "scripts/sdd_session.py"])[0]
        self.assertIn("skills/new/SKILL.md", message)
        self.assertIn(".claude-plugin/plugin.json", message)
        self.assertIn(".codex-plugin/plugin.json", message)

    def test_a_long_list_is_truncated_but_counted(self) -> None:
        paths = [f"skills/s{n}/SKILL.md" for n in range(9)]
        message = self.guard(paths)[0]
        self.assertIn("9 distributed file(s)", message)
        self.assertIn("…", message)

    def test_nothing_changed_is_not_a_failure(self) -> None:
        self.assertEqual([], self.guard([]))


if __name__ == "__main__":
    unittest.main()
