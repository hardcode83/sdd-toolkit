from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sdd-doctor.py"
FIXTURES = Path(__file__).parent / "fixtures"


class DoctorFixtureTests(unittest.TestCase):
    maxDiff = None

    def run_doctor(self, fixture: str) -> subprocess.CompletedProcess[str]:
        fixture_root = FIXTURES / fixture
        before = {
            path.relative_to(fixture_root): path.read_bytes()
            for path in sorted(fixture_root.rglob("*"))
            if path.is_file()
        }
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(fixture_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        after = {
            path.relative_to(fixture_root): path.read_bytes()
            for path in sorted(fixture_root.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(before, after, "sdd doctor modified its fixture")
        self.assertEqual("", result.stderr)
        return result

    def assert_diagnostic(
        self, fixture: str, exit_code: int, code: str, severity: str
    ) -> str:
        result = self.run_doctor(fixture)
        self.assertEqual(exit_code, result.returncode, result.stdout)
        self.assertIn(f"{severity} {code} ", result.stdout)
        self.assertIn("Suggested action:", result.stdout)
        return result.stdout

    def test_valid_repository(self) -> None:
        first = self.run_doctor("valid")
        second = self.run_doctor("valid")
        self.assertEqual(0, first.returncode)
        self.assertEqual("sdd doctor: 0 error(s), 0 warning(s)\n", first.stdout)
        self.assertEqual(first.stdout, second.stdout)

    def test_valid_lifecycle_managed_repository(self) -> None:
        first = self.run_doctor("lifecycle-valid")
        second = self.run_doctor("lifecycle-valid")
        self.assertEqual(0, first.returncode, first.stdout)
        self.assertEqual("sdd doctor: 0 error(s), 0 warning(s)\n", first.stdout)
        self.assertEqual(first.stdout, second.stdout)

    def test_roadmap_desynchronized(self) -> None:
        output = self.assert_diagnostic(
            "roadmap-missing-change", 1, "SDD002", "ERROR"
        )
        self.assertIn("sdd/roadmap.md:3", output)

    def test_archived_change_still_pending(self) -> None:
        output = self.assert_diagnostic(
            "archived-pending-roadmap", 1, "SDD001", "ERROR"
        )
        self.assertIn("Archived change 'finished-feature' remains unchecked", output)

    def test_active_change_without_proposal(self) -> None:
        output = self.assert_diagnostic(
            "active-missing-proposal", 1, "SDD003", "ERROR"
        )
        self.assertIn("has no mandatory proposal.md", output)

    def test_requirement_without_task(self) -> None:
        output = self.assert_diagnostic(
            "requirement-without-task", 1, "SDD005", "ERROR"
        )
        self.assertIn("Requirement 'R2' has no associated task", output)

    def test_task_with_unknown_requirement(self) -> None:
        output = self.assert_diagnostic(
            "task-unknown-requirement", 1, "SDD004", "ERROR"
        )
        self.assertIn("Task cites undefined requirement 'R9'", output)

    def test_archive_with_pending_tasks_is_warning(self) -> None:
        output = self.assert_diagnostic(
            "archive-pending-tasks", 0, "SDD006", "WARNING"
        )
        self.assertIn("0 error(s), 1 warning(s)", output)

    def test_archive_with_blocked_file_is_warning(self) -> None:
        output = self.assert_diagnostic(
            "archive-blocked", 0, "SDD007", "WARNING"
        )
        self.assertIn("still contains an active BLOCKED.md", output)

    def test_missing_local_reference_is_warning(self) -> None:
        output = self.assert_diagnostic(
            "missing-local-reference", 0, "SDD008", "WARNING"
        )
        self.assertIn("sdd/specs/example.md:9", output)

    def test_change_duplicated_between_active_and_archive(self) -> None:
        output = self.assert_diagnostic(
            "duplicate-change", 1, "SDD009", "ERROR"
        )
        self.assertIn("exists as both active and archived", output)

    def test_managed_archive_without_merge_evidence(self) -> None:
        output = self.assert_diagnostic(
            "archive-missing-merge", 1, "SDD010", "ERROR"
        )
        self.assertIn("lacks complete merge evidence", output)

    def test_ready_for_pr_cannot_live_in_archive(self) -> None:
        output = self.assert_diagnostic(
            "ready-in-archive", 1, "SDD011", "ERROR"
        )
        self.assertIn("READY_FOR_PR change is already located in archive", output)

    def test_incompatible_lifecycle_fields(self) -> None:
        result = self.run_doctor("lifecycle-invalid")
        self.assertEqual(1, result.returncode, result.stdout)
        for code in ("SDD012", "SDD013", "SDD014", "SDD015"):
            self.assertIn(f"ERROR {code} ", result.stdout)


if __name__ == "__main__":
    unittest.main()
