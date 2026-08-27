from __future__ import annotations

import unittest

from tests.test_reviewer_plan import ROOT, load_module
from tests.test_reviewer_adapters import FakeClaude, FakeCodex


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
        claude = FakeClaude([{"reviewer_id": item.reviewer_id, "scope_id": item.scope_id, "verdict": "PASS", "findings": [], "evidence": ["src/a.py"], "status": "complete"} for item in claude_plan])
        codex = FakeCodex(claude.payloads)
        self.rp.dispatch_claude_panel(claude_plan, claude, "x", refs)
        self.rp.dispatch_codex_panel(codex_plan, codex, "x", ROOT, refs)
        self.assertEqual([p.reviewer_id for p in claude_plan[:3]], expected)
        self.assertEqual([p.reviewer_id for p in codex_plan[:3]], expected)
        self.assertEqual([request["reviewer_id"] for request in codex.requests[0]], [request.splitlines()[0].split(": ", 1)[1] for request in claude.requests[0]])
        self.assertEqual(len(codex.requests), 1)

    def test_solo_has_no_provider_dispatch(self):
        self.assertEqual(self.rp.build_reviewer_plan(ROOT, "run", {"feature": "x", "files": ["src/a.py"]}, solo=True), [])


if __name__ == "__main__":
    unittest.main()
