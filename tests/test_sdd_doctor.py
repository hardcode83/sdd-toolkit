from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_toolkit import (  # noqa: E402
    fixture_contract_errors,
    load_expectations,
    run_doctor,
)


class DoctorFixtureTests(unittest.TestCase):
    def test_all_registered_fixtures_match_the_executable_contract(self) -> None:
        self.assertEqual([], fixture_contract_errors())

    def test_fixture_registry_covers_every_published_diagnostic(self) -> None:
        diagnostics = {
            item
            for expectation in load_expectations().values()
            for item in expectation["diagnostics"]
        }
        codes = {item.split()[1] for item in diagnostics}
        self.assertEqual({f"SDD{number:03d}" for number in range(1, 25)}, codes)

    def test_valid_fixtures_cover_legacy_and_lifecycle_managed_archives(self) -> None:
        expectations = load_expectations()
        self.assertEqual(
            {"exit_code": 0, "diagnostics": []},
            expectations["valid"],
        )
        self.assertEqual(
            {"exit_code": 0, "diagnostics": []},
            expectations["lifecycle-valid"],
        )

    def test_doctor_accepts_projects_without_a_python_assumption(self) -> None:
        stacks = (
            ("python", {"pyproject.toml": "[project]\nname = 'example'\n"}),
            ("typescript", {"package.json": '{"scripts":{"test":"npm test"}}\n'}),
            ("go", {"go.mod": "module example\n"}),
            ("java", {"pom.xml": "<project />\n"}),
            ("undefined", {}),
        )
        for stack, marker in stacks:
            with self.subTest(stack=stack), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = (
                    root
                    / "sdd"
                    / "changes"
                    / "archive"
                    / "2026-01-01-example"
                )
                archive.mkdir(parents=True)
                (root / "sdd" / "project.md").write_text(
                    "# Project\n\n## Stack\n\n"
                    f"Detected stack: {stack}\n",
                    encoding="utf-8",
                )
                (root / "sdd" / "roadmap.md").write_text(
                    "- [x] example → changes/archive/2026-01-01-example/\n",
                    encoding="utf-8",
                )
                (archive / "proposal.md").write_text(
                    "# Proposal\n\n### R1 — Example\n",
                    encoding="utf-8",
                )
                (archive / "tasks.md").write_text(
                    "- [x] 1.1 Complete [R1]\n",
                    encoding="utf-8",
                )
                for filename, content in marker.items():
                    (root / filename).write_text(content, encoding="utf-8")
                result = run_doctor(root)
                self.assertEqual(0, result.returncode, result.stdout)


class WorktreeIgnoreTests(unittest.TestCase):
    """SDD024 must ask git, not just read .gitignore."""

    def project(self, root: Path) -> None:
        (root / "sdd").mkdir()
        (root / "sdd" / "project.md").write_text("# Project\n", encoding="utf-8")
        (root / "sdd" / "roadmap.md").write_text(
            "# Roadmap\n\n- [ ] alpha — pendiente\n", encoding="utf-8"
        )
        (root / ".claude" / "worktrees" / "alpha").mkdir(parents=True)
        subprocess.run(
            ["git", "init", "-q", "."], cwd=root, check=True, capture_output=True
        )

    def diagnose(self, root: Path) -> list[str]:
        result = run_doctor(root)
        return [line for line in result.stdout.splitlines() if "SDD024" in line]

    def test_an_unignored_worktree_directory_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(root)
            self.assertEqual(1, len(self.diagnose(root)))

    def test_gitignore_silences_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(root)
            (root / ".gitignore").write_text(".claude/worktrees/\n", encoding="utf-8")
            self.assertEqual([], self.diagnose(root))

    def test_git_info_exclude_silences_it_too(self) -> None:
        """A machine-local exclude is a legitimate way to ignore a local dir —
        reading only .gitignore reported a correct project as broken."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(root)
            exclude = root / ".git" / "info" / "exclude"
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text(".claude/worktrees/\n", encoding="utf-8")
            self.assertEqual([], self.diagnose(root))

    def test_no_worktrees_directory_means_no_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "sdd").mkdir()
            (root / "sdd" / "project.md").write_text("# Project\n", encoding="utf-8")
            (root / "sdd" / "roadmap.md").write_text(
                "# Roadmap\n\n- [ ] alpha — pendiente\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "init", "-q", "."], cwd=root, check=True, capture_output=True
            )
            self.assertEqual([], self.diagnose(root))


if __name__ == "__main__":
    unittest.main()
