from __future__ import annotations

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
        self.assertEqual({f"SDD{number:03d}" for number in range(1, 24)}, codes)

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


if __name__ == "__main__":
    unittest.main()
