from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_toolkit import (  # noqa: E402
    validate_manifests,
    validate_project_boundary,
    validate_skills,
)


class ToolkitStructureTests(unittest.TestCase):
    def test_manifests_are_valid(self) -> None:
        self.assertEqual([], validate_manifests())

    def test_skills_are_valid_and_references_resolve(self) -> None:
        self.assertEqual([], validate_skills())

    def test_plugin_and_consumer_assets_have_an_explicit_boundary(self) -> None:
        self.assertEqual([], validate_project_boundary())


if __name__ == "__main__":
    unittest.main()
