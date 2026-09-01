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


class IsolationPolicyTests(unittest.TestCase):
    """SDD026, and the half of SDD024 that has to arrive before the directory.

    The policy is committed project state — unlike the session registry — so the
    doctor can and must validate it: a typo degrades to the old behaviour without
    a word, which is the failure this change exists to remove (ADR 0002).
    """

    def project(self, root: Path, policy: str, gitignore: bool = True) -> None:
        (root / "sdd").mkdir()
        (root / "sdd" / "project.md").write_text(
            f"# Project\n\n## Worktree bootstrap\n\n{policy}\n", encoding="utf-8"
        )
        (root / "sdd" / "roadmap.md").write_text(
            "# Roadmap\n\n- [ ] alpha — pendiente\n", encoding="utf-8"
        )
        if gitignore:
            (root / ".gitignore").write_text(".claude/worktrees/\n", encoding="utf-8")
        subprocess.run(
            ["git", "init", "-q", "."], cwd=root, check=True, capture_output=True
        )

    def diagnose(self, root: Path, code: str) -> list[str]:
        return [line for line in run_doctor(root).stdout.splitlines() if code in line]

    def test_a_recognised_policy_is_not_reported(self) -> None:
        for declared in ("isolation: always", "isolation: on-conflict"):
            with self.subTest(declared=declared), tempfile.TemporaryDirectory() as d:
                root = Path(d).resolve()
                self.project(root, declared)
                self.assertEqual([], self.diagnose(root, "SDD026"))

    def test_a_typo_is_an_error_that_names_the_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(root, "isolation: alway")
            reported = self.diagnose(root, "SDD026")
            self.assertEqual(1, len(reported), reported)
            self.assertIn("ERROR", reported[0])
            self.assertIn("sdd/project.md:5", reported[0])
            self.assertEqual(1, run_doctor(root).returncode)

    def test_always_warns_about_gitignore_before_the_directory_exists(self) -> None:
        """Afterwards is too late: the nested checkout is already committable."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(root, "isolation: always", gitignore=False)
            self.assertFalse((root / ".claude" / "worktrees").exists())
            reported = self.diagnose(root, "SDD024")
            self.assertEqual(1, len(reported), reported)
            self.assertIn("isolation: always", reported[0])

    def test_on_conflict_keeps_waiting_for_a_real_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(root, "isolation: on-conflict", gitignore=False)
            self.assertEqual([], self.diagnose(root, "SDD024"))


class RoadmapIndexBudgetTests(unittest.TestCase):
    """SDD025: the roadmap is an index, and every phase pays its size.

    A real project's roadmap reached 95 KB — read by new, run, review, auto and
    status alike, on every run — because entries kept their whole rationale
    instead of pointing at sdd/roadmap/<feature>.md.
    """

    def project(self, root: Path, entries: str) -> None:
        (root / "sdd").mkdir()
        (root / "sdd" / "project.md").write_text("# Project\n", encoding="utf-8")
        (root / "sdd" / "roadmap.md").write_text(
            f"# Roadmap\n\n{entries}", encoding="utf-8"
        )
        subprocess.run(
            ["git", "init", "-q", "."], cwd=root, check=True, capture_output=True
        )

    def diagnose(self, root: Path) -> list[str]:
        result = run_doctor(root)
        return [line for line in result.stdout.splitlines() if "SDD025" in line]

    def test_a_scannable_index_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(root, "- [ ] alpha — pendiente\n")
            self.assertEqual([], self.diagnose(root))

    def test_an_index_carrying_its_rationale_is_reported_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            body = "  " + ("razonamiento largo " * 40) + "\n"
            self.project(
                root, "".join(f"- [ ] f{n} — pendiente\n{body}" for n in range(60))
            )
            reported = self.diagnose(root)
            self.assertEqual(1, len(reported), reported)
            self.assertIn("WARNING", reported[0])

    def test_it_is_a_warning_not_a_failure(self) -> None:
        """Size is a cost to fix deliberately, never a reason to block a run."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            body = "  " + ("razonamiento largo " * 40) + "\n"
            self.project(
                root, "".join(f"- [ ] f{n} — pendiente\n{body}" for n in range(60))
            )
            self.assertEqual(0, run_doctor(root).returncode)


class SteeringBudgetTests(unittest.TestCase):
    """SDD027: a steering doc is loaded whole by every phase it applies to.

    A real project's `steering/security.md` reached 93 KB (~23k tokens, 285
    lines) and was read in full by design, by run and by the security reviewer of
    every panel. Selective loading only helps across files, so size is the one
    thing the doctor can see.
    """

    def project(self, root: Path, lines: int) -> None:
        (root / "sdd" / "steering").mkdir(parents=True)
        (root / "sdd" / "project.md").write_text("# Project\n", encoding="utf-8")
        body = "".join(f"- regla {n}: no hagas eso\n" for n in range(lines))
        (root / "sdd" / "steering" / "security.md").write_text(
            f"---\nphases: [design, run]\n---\n\n# Security\n\n{body}", encoding="utf-8"
        )
        subprocess.run(
            ["git", "init", "-q", "."], cwd=root, check=True, capture_output=True
        )

    def diagnose(self, root: Path) -> list[str]:
        result = run_doctor(root)
        return [line for line in result.stdout.splitlines() if "SDD027" in line]

    def test_a_focused_doc_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(root, 60)
            self.assertEqual([], self.diagnose(root))

    def test_a_doc_over_budget_is_reported_once_with_its_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(root, 300)
            reported = self.diagnose(root)
            self.assertEqual(1, len(reported), reported)
            self.assertIn("WARNING", reported[0])
            self.assertIn("security.md", reported[0])
            self.assertIn("lines", reported[0])

    def test_it_is_a_warning_not_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(root, 300)
            self.assertEqual(0, run_doctor(root).returncode)


class ProjectReviewerMetadataTests(unittest.TestCase):
    """SDD028: a project reviewer without applies_to/phases runs on every panel.

    Four such reviewers in a real project turned a 13-section run into 91
    reviewer launches; the planner can only skip on a definitive NO MATCH.
    """

    def project(self, root: Path, frontmatter: str) -> None:
        (root / "sdd").mkdir()
        (root / "sdd" / "project.md").write_text("# Project\n", encoding="utf-8")
        agents = root / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "sdd-review-i18n.md").write_text(
            f"---\n{frontmatter}---\n\nYou are the i18n reviewer.\n", encoding="utf-8"
        )
        subprocess.run(
            ["git", "init", "-q", "."], cwd=root, check=True, capture_output=True
        )

    def diagnose(self, root: Path) -> list[str]:
        result = run_doctor(root)
        return [line for line in result.stdout.splitlines() if "SDD028" in line]

    def test_a_reviewer_with_metadata_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(
                root,
                "name: sdd-review-i18n\ndescription: i18n\nmodel: haiku\n"
                "phases: [run, review, auto]\napplies_to: [\"frontend/**\"]\n",
            )
            self.assertEqual([], self.diagnose(root))

    def test_a_reviewer_without_metadata_is_reported_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(root, "name: sdd-review-i18n\ndescription: i18n\nmodel: haiku\n")
            reported = self.diagnose(root)
            self.assertEqual(1, len(reported), reported)
            self.assertIn("WARNING", reported[0])
            self.assertIn("applies_to", reported[0])

    def test_it_is_a_warning_not_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.project(root, "name: sdd-review-i18n\ndescription: i18n\n")
            self.assertEqual(0, run_doctor(root).returncode)


if __name__ == "__main__":
    unittest.main()
