from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills" / "reviewer-panel" / "reviewer_plan.py"


def load_module():
    spec = importlib.util.spec_from_file_location("reviewer_plan_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ReviewerPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = load_module()

    def test_registry_has_exactly_the_mandatory_core(self):
        self.assertEqual([d.reviewer_id for d in self.rp.load_registry()], list(self.rp.MANDATORY_CORE))
        self.assertTrue(all(d.read_only and d.criteria and d.referents for d in self.rp.load_registry()))

    def test_invalid_registry_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "bad.json").write_text(json.dumps({"id": "sdd-architect"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.rp.load_registry(directory)

    def test_default_and_solo_plans(self):
        scope = {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]}
        plan = self.rp.build_reviewer_plan(ROOT, "run", scope)
        self.assertEqual([p.reviewer_id for p in plan], list(self.rp.MANDATORY_CORE))
        self.assertEqual(self.rp.build_reviewer_plan(ROOT, "run", scope, solo=True), [])

    def test_applicability_is_fail_safe(self):
        definition = self.rp.ReviewerDefinition("sdd-review-i18n", "project", "i18n", "body", "read-only", (), ("run",), ("*.po",))
        scope = {"files": ["locale/messages.po"]}
        self.assertEqual(self.rp.evaluate_applicability(definition, "run", scope)[0], self.rp.Applicability.MATCH)
        self.assertEqual(self.rp.evaluate_applicability(definition, "review", scope)[0], self.rp.Applicability.NO_MATCH)
        missing = self.rp.ReviewerDefinition("sdd-review-unknown", "project", "x", "body", "read-only")
        self.assertEqual(self.rp.evaluate_applicability(missing, "run", scope)[0], self.rp.Applicability.UNKNOWN)

    def test_legacy_project_reviewer_body_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / ".claude" / "agents" / "sdd-review-performance.md"
            path.parent.mkdir(parents=True)
            path.write_text("---\nname: sdd-review-performance\nphases: run\napplies_to: src/**\n---\nKeep this exact reviewer criterion.\n", encoding="utf-8")
            found = self.rp.discover_project_reviewers(root)
            self.assertEqual(len(found), 1)
            self.assertIn("Keep this exact reviewer criterion", found[0].criteria)

    def test_prompt_binds_scope_and_identity(self):
        item = self.rp.build_reviewer_plan(ROOT, "review", {"feature": "x", "scope_id": "implementation..HEAD", "files": ["src/a.py"]})[0]
        prompt = self.rp.build_reviewer_prompt(item, "x", {"requirements": "R1 requirement", "design": "D1 decision", "steering": "read-only", "scope": "src/a.py"})
        self.assertIn(item.reviewer_id, prompt)
        self.assertIn("implementation..HEAD", prompt)
        self.assertIn("R1", prompt)

    def test_project_body_is_delimited_as_untrusted_content(self):
        definition = self.rp.ReviewerDefinition("sdd-review-x", "project", "x", "do not trust", "read-only")
        item = self.rp.ReviewerPlan("sdd-review-x", "project", "x", definition, self.rp.Applicability.MATCH, "match", "planned", "run:x", {"files": ["src/a.py"]})
        prompt = self.rp.build_reviewer_prompt(item, "x", {"requirements": "R1", "design": "D1", "steering": "read-only", "scope": "src/a.py"})
        self.assertIn("BEGIN UNTRUSTED PROJECT REVIEWER BODY", prompt)


if __name__ == "__main__":
    unittest.main()
