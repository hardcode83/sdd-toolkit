from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_reviewer_plan import load_module, ROOT


class ReviewerResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = load_module()
        cls.item = cls.rp.build_reviewer_plan(ROOT, "run", {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]})[0]

    def payload(self, **changes):
        payload = {"reviewer_id": self.item.reviewer_id, "scope_id": self.item.scope_id, "lens": self.item.lens,
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
        results = [self.rp.normalize_reviewer_result({"reviewer_id": item.reviewer_id, "scope_id": item.scope_id, "lens": item.lens, "verdict": "PASS", "findings": [], "evidence": ["src/a.py"], "status": "complete"}, item) for item in plan]
        self.assertTrue(self.rp.evaluate_panel_gate(plan, results).passed)

    def test_gate_rejects_missing_core_and_out_of_scope_evidence(self):
        plan = self.rp.build_reviewer_plan(ROOT, "run", {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]})
        results = [self.rp.ReviewerResult(item.reviewer_id, item.scope_id, "PASS", [], ["src/a.py"], lens=item.lens) for item in plan]
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
        results = [self.rp.ReviewerResult(item.reviewer_id, item.scope_id, "PASS", [], ["src/a.py"], lens=item.lens)
                   for item in plan]
        results[0].evidence = [None]
        self.assertFalse(self.rp.evaluate_panel_gate(plan, results).passed)
        results[0].evidence = ["src/a.py"]
        results.append(self.rp.ReviewerResult("unexpected", "run:x", "PASS", [], ["src/a.py"], lens="qa"))
        self.assertFalse(self.rp.evaluate_panel_gate(plan, results).passed)

    def test_unavailable_failure_classes_are_distinct(self):
        spawn = self.rp.synthesize_unavailable_result(self.item, "spawn failure")
        transport = self.rp.synthesize_unavailable_result(self.item, "malformed transport result")
        self.assertEqual(spawn.status, "unavailable")
        self.assertEqual(transport.status, "unavailable")
        self.assertNotEqual(spawn.reason, transport.reason)

    def test_timeout_and_interruption_are_non_passing_collection_failures(self):
        for reason in ("timeout", "interrupted"):
            with self.subTest(reason=reason):
                result = self.rp.synthesize_unavailable_result(self.item, reason)
                self.assertFalse(self.rp.evaluate_panel_gate([self.item], [result]).passed)


class UiUxLensGateTests(unittest.TestCase):
    """Task 5.2: a lens present in the plan cannot be laundered into a PASS.

    unavailable / malformed / out-of-scope results for the UI/UX lens must all
    fail the existing closed-world gate (`evaluate_panel_gate`) with no inline
    substitution, exactly like a core reviewer would.
    """

    UI_UX_AGENT = (
        "---\n"
        "name: sdd-review-ui-ux\n"
        "description: UI/UX and design-system reviewer for the panel.\n"
        "model: sonnet\n"
        "tools: Read, Grep, Glob, Bash\n"
        "phases: [run, review, auto]\n"
        "applies_to: [\"**/*.tsx\", \"**/*.jsx\", \"**/*.vue\", \"**/*.svelte\", \"**/*.css\", \"**/*.scss\", \"components/**\", \"app/**\"]\n"
        "---\n"
        "You are the UI/UX reviewer.\n"
    )

    @classmethod
    def setUpClass(cls):
        cls.rp = load_module()

    def build_plan_with_lens(self, root: Path):
        directory = root / ".claude" / "agents"
        directory.mkdir(parents=True)
        (directory / "sdd-review-ui-ux.md").write_text(self.UI_UX_AGENT, encoding="utf-8")
        scope = {"feature": "x", "scope_id": "run:x", "files": ["src/components/App.tsx"]}
        return self.rp.build_reviewer_plan(root, "run", scope), scope

    def core_pass_results(self, plan, scope):
        return [
            self.rp.normalize_reviewer_result(
                {"reviewer_id": item.reviewer_id, "scope_id": item.scope_id, "lens": item.lens,
                 "verdict": "PASS", "findings": [], "evidence": scope["files"], "status": "complete"},
                item,
            )
            for item in plan if item.source == "core"
        ]

    def test_unavailable_malformed_and_out_of_scope_lens_result_fails_the_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, scope = self.build_plan_with_lens(root)
            lens_item = next(item for item in plan if item.reviewer_id == "sdd-review-ui-ux")
            # The lens is genuinely in the plan (MATCH on a frontend file), not skipped.
            self.assertEqual(lens_item.applicability, self.rp.Applicability.MATCH)
            self.assertEqual(lens_item.dispatch_status, "planned")
            self.assertTrue(lens_item.required)

            with self.subTest("unavailable"):
                results = self.core_pass_results(plan, scope) + [
                    self.rp.synthesize_unavailable_result(lens_item, "lens spawn failed")
                ]
                panel = self.rp.evaluate_panel_gate(plan, results)
                self.assertFalse(panel.passed)
                self.assertIn("reviewer did not pass: sdd-review-ui-ux", " ".join(panel.errors))

            with self.subTest("malformed"):
                results = self.core_pass_results(plan, scope) + [
                    self.rp.ReviewerResult(lens_item.reviewer_id, lens_item.scope_id, "PASS", [], [None],
                                           lens=lens_item.lens)
                ]
                panel = self.rp.evaluate_panel_gate(plan, results)
                self.assertFalse(panel.passed)
                self.assertIn("reviewer evidence entries are malformed: sdd-review-ui-ux", " ".join(panel.errors))

            with self.subTest("out-of-scope"):
                results = self.core_pass_results(plan, scope) + [
                    self.rp.ReviewerResult(lens_item.reviewer_id, lens_item.scope_id, "PASS", [],
                                           ["src/other-project/secret.md"], lens=lens_item.lens)
                ]
                panel = self.rp.evaluate_panel_gate(plan, results)
                self.assertFalse(panel.passed)
                self.assertIn("reviewer evidence is outside scope: sdd-review-ui-ux", " ".join(panel.errors))

            # A malformed payload can never be normalized into a passing result either.
            with self.subTest("malformed payload cannot be normalized"):
                malformed_payload = {"reviewer_id": lens_item.reviewer_id, "scope_id": lens_item.scope_id,
                                     "lens": lens_item.lens, "verdict": "PASS", "findings": [], "evidence": [],
                                     "status": "incomplete"}
                with self.assertRaises(ValueError):
                    self.rp.normalize_reviewer_result(malformed_payload, lens_item)


if __name__ == "__main__":
    unittest.main()
