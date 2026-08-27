from __future__ import annotations

import unittest

from tests.test_reviewer_plan import ROOT, load_module


class LifecyclePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = load_module()

    def scope(self, phase):
        return {"feature": "x", "scope_id": f"{phase}:x", "files": ["src/a.py"]}

    def adapter(self, plan, **kwargs):
        results = [self.rp.ReviewerResult(item.reviewer_id, item.scope_id, "PASS", [], ["src/a.py"]) for item in plan]
        return self.rp.PanelResult(plan, results, "PASS", [])

    def test_run_review_and_auto_use_one_executable_gate(self):
        for phase, function in (("run", self.rp.run_panel), ("review", self.rp.review_panel), ("auto", self.rp.auto_panel)):
            with self.subTest(phase=phase):
                self.assertTrue(function(ROOT, "x", self.scope(phase), self.adapter).passed)

    def test_solo_bypasses_and_cannot_pass(self):
        self.assertFalse(self.rp.run_panel(ROOT, "x", self.scope("run"), self.adapter, solo=True).passed)

    def test_adapter_failure_and_bypass_attempt_fail_closed(self):
        def broken(plan, **kwargs):
            return {"gate": "PASS"}
        self.assertFalse(self.rp.review_panel(ROOT, "x", self.scope("review"), broken).passed)

        def bypass(plan, **kwargs):
            return self.rp.PanelResult(plan, [], "PASS", [])
        self.assertFalse(self.rp.auto_panel(ROOT, "x", self.scope("auto"), bypass).passed)


if __name__ == "__main__":
    unittest.main()
