from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_reviewer_plan import load_module, ROOT


class ReviewerResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = load_module()
        cls.item = cls.rp.build_reviewer_plan(ROOT, "run", {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]})[0]

    def payload(self, **changes):
        payload = {"reviewer_id": self.item.reviewer_id, "scope_id": self.item.scope_id,
                   "verdict": "PASS", "findings": [], "evidence": ["src/a.py"], "status": "complete"}
        payload.update(changes)
        return payload

    def test_valid_pass_and_fail(self):
        self.assertEqual(self.rp.normalize_reviewer_result(self.payload(), self.item).verdict, "PASS")
        result = self.rp.normalize_reviewer_result(self.payload(verdict="FAIL", findings=["issue"], evidence=[]), self.item)
        self.assertEqual(result.verdict, "FAIL")

    def test_malformed_identity_scope_and_missing_evidence_fail(self):
        for changes in ({"reviewer_id": "spoof"}, {"scope_id": "other"}, {"evidence": []}, {"status": "unavailable"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.rp.normalize_reviewer_result(self.payload(**changes), self.item)

    def test_unavailable_and_incomplete_sets_cannot_pass(self):
        plan = self.rp.build_reviewer_plan(ROOT, "run", {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]})
        unavailable = [self.rp.synthesize_unavailable_result(item, "spawn failed") for item in plan]
        panel = self.rp.evaluate_panel_gate(plan, unavailable)
        self.assertFalse(panel.passed)
        self.assertIn("reviewer did not pass", " ".join(panel.errors))
        self.assertFalse(self.rp.evaluate_panel_gate(plan, []).passed)

    def test_complete_pass_set_passes(self):
        plan = self.rp.build_reviewer_plan(ROOT, "run", {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]})
        results = [self.rp.normalize_reviewer_result({"reviewer_id": item.reviewer_id, "scope_id": item.scope_id, "verdict": "PASS", "findings": [], "evidence": ["src/a.py"], "status": "complete"}, item) for item in plan]
        self.assertTrue(self.rp.evaluate_panel_gate(plan, results).passed)

    def test_gate_rejects_missing_core_and_out_of_scope_evidence(self):
        plan = self.rp.build_reviewer_plan(ROOT, "run", {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]})
        results = [self.rp.ReviewerResult(item.reviewer_id, item.scope_id, "PASS", [], ["src/a.py"]) for item in plan]
        self.assertFalse(self.rp.evaluate_panel_gate(plan[1:], results[1:]).passed)
        results[0].evidence = ["sdd/changes/other/secret.md"]
        self.assertFalse(self.rp.evaluate_panel_gate(plan, results).passed)

    def test_failure_matrix_never_passes(self):
        cases = (
            ("malformed", None),
            ("wrong scope", {"scope_id": "wrong"}),
            ("wrong identity", {"reviewer_id": "spoof"}),
            ("bad findings", {"findings": "not-list"}),
            ("incomplete", {"status": "incomplete"}),
            ("missing evidence", {"evidence": []}),
            ("out of scope", {"evidence": ["src/other.py"]}),
        )
        for name, changes in cases:
            with self.subTest(name=name):
                payload = None if changes is None else self.payload(**changes)
                with self.assertRaises((TypeError, ValueError)):
                    self.rp.normalize_reviewer_result(payload, self.item)

    def test_gate_rejects_malformed_typed_results_and_extra_identity(self):
        plan = self.rp.build_reviewer_plan(ROOT, "run", {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]})
        results = [self.rp.ReviewerResult(item.reviewer_id, item.scope_id, "PASS", [], ["src/a.py"])
                   for item in plan]
        results[0].evidence = [None]
        self.assertFalse(self.rp.evaluate_panel_gate(plan, results).passed)
        results[0].evidence = ["src/a.py"]
        results.append(self.rp.ReviewerResult("unexpected", "run:x", "PASS", [], ["src/a.py"]))
        self.assertFalse(self.rp.evaluate_panel_gate(plan, results).passed)

    def test_unavailable_failure_classes_are_distinct(self):
        spawn = self.rp.synthesize_unavailable_result(self.item, "spawn failure")
        transport = self.rp.synthesize_unavailable_result(self.item, "malformed transport result")
        self.assertEqual(spawn.status, "unavailable")
        self.assertEqual(transport.status, "unavailable")
        self.assertNotEqual(spawn.reason, transport.reason)


if __name__ == "__main__":
    unittest.main()
