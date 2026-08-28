from __future__ import annotations

import unittest

from tests.test_reviewer_plan import ROOT, load_module
from tests.test_reviewer_adapters import FakeClaude


class ReviewerParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = load_module()

    def test_provider_requests_are_derived_from_registry_plan(self):
        scope = {"feature": "x", "scope_id": "review:change", "files": ["src/a.py"]}
        claude_plan = self.rp.build_reviewer_plan(ROOT, "review", dict(scope))
        codex_plan = self.rp.build_reviewer_plan(ROOT, "review", dict(scope))
        expected = [d.reviewer_id for d in self.rp.load_registry()]
        refs = {"requirements": "R1", "design": "D1", "steering": "read-only", "scope": "src/a.py"}
        claude = FakeClaude([{"reviewer_id": item.reviewer_id, "scope_id": item.scope_id, "lens": item.lens, "verdict": "PASS", "findings": [], "evidence": ["src/a.py"], "status": "complete"} for item in claude_plan])
        self.rp.dispatch_claude_panel(claude_plan, claude, "x", refs)
        handoff = self.rp.build_codex_handoff(codex_plan, "x", ROOT, refs)
        handoff["bindings"] = {f"h{i}": item.reviewer_id for i, item in enumerate(codex_plan)}
        handoff["waited"] = list(handoff["bindings"])
        handoff["results"] = [{"handle": f"h{i}", "payload": payload} for i, payload in enumerate(claude.payloads)]
        self.rp.dispatch_codex_panel(codex_plan, handoff, "x", ROOT, refs, baseline="clean", final_snapshot="clean")
        self.assertEqual([p.reviewer_id for p in claude_plan[:3]], expected)
        self.assertEqual([p.reviewer_id for p in codex_plan[:3]], expected)
        self.assertEqual([request["reviewer_id"] for request in handoff["requests"]], [next(line.split(": ", 1)[1] for line in request.splitlines() if line.startswith("Reviewer identity:")) for request in claude.requests[0]])

    def test_solo_has_no_provider_dispatch(self):
        self.assertEqual(self.rp.build_reviewer_plan(ROOT, "run", {"feature": "x", "files": ["src/a.py"]}, solo=True), [])

    def test_all_supported_phases_derive_the_same_core_plan(self):
        scopes = {
            "run": {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]},
            "review": {"feature": "x", "scope_id": "implementation..HEAD", "files": ["src/a.py"]},
            "auto": {"feature": "x", "scope_id": "auto:x", "files": ["src/a.py"]},
        }
        expected = {item.reviewer_id for item in self.rp.load_registry()}
        for phase, scope in scopes.items():
            with self.subTest(phase=phase):
                self.assertEqual({item.reviewer_id for item in self.rp.build_reviewer_plan(ROOT, phase, scope)[:3]}, expected)

    def test_r6_change_and_drift_and_auto_inputs_use_both_provider_boundaries(self):
        cases = (
            ("run", "run:x", ["src/a.py"]),
            ("review", "implementation..HEAD", ["src/a.py"]),
            ("review", "specs..HEAD", ["sdd/specs/example.md"]),
            ("auto", "auto:inline", ["src/a.py"]),
            ("auto", "auto:delegated", ["src/a.py"]),
            ("auto", "auto:pr-open", ["src/a.py"]),
        )
        registry_ids = [item.reviewer_id for item in self.rp.load_registry()]
        refs = {"requirements": "R6", "design": "D9", "steering": "read-only", "scope": "scope"}
        for phase, scope_id, files in cases:
            with self.subTest(phase=phase, scope_id=scope_id):
                scope = {"feature": "x", "scope_id": scope_id, "files": files}
                plan = self.rp.build_reviewer_plan(ROOT, phase, scope)
                self.assertEqual([item.reviewer_id for item in plan[:3]], registry_ids)
                fake = FakeClaude([{"reviewer_id": item.reviewer_id, "scope_id": item.scope_id,
                                    "lens": item.lens, "verdict": "PASS", "findings": [],
                                    "evidence": [files[0]], "status": "complete"} for item in plan])
                self.assertTrue(self.rp.dispatch_claude_panel(plan, fake, "x", refs).passed)
                handoff = self.rp.build_codex_handoff(plan, "x", ROOT, refs)
                handoff["bindings"] = {f"h{i}": item.reviewer_id for i, item in enumerate(plan)}
                handoff["waited"] = list(handoff["bindings"])
                handoff["results"] = [{"handle": f"h{i}", "payload": payload}
                                       for i, payload in enumerate(fake.payloads)]
                self.assertTrue(self.rp.dispatch_codex_panel(plan, handoff, "x", ROOT, refs,
                                                             baseline="clean", final_snapshot="clean").passed)


if __name__ == "__main__":
    unittest.main()
