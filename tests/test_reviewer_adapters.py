from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_reviewer_plan import load_module, ROOT


class FakeClaude:
    def __init__(self, payloads):
        self.payloads, self.requests = payloads, []

    def launch_batch(self, requests):
        self.requests.append(requests)
        return self.payloads


class FakeCodex:
    def __init__(self, payloads, mutate=False):
        self.payloads, self.mutate = payloads, mutate
        self.requests, self.waited, self.collected = [], [], []

    def snapshot(self, worktree):
        return "mutated" if self.mutate and self.collected else "clean"

    def worktree_root(self):
        return ROOT

    def capabilities(self):
        return {"parallel_spawn", "wait", "collection", "read_only", "worktree_binding", "no_lifecycle_commands", "no_network"}

    def spawn_batch(self, requests):
        self.requests.append(requests)
        return [(f"h{i}", request["reviewer_id"]) for i, request in enumerate(requests)]

    def wait(self, handle):
        self.waited.append(handle)

    def collect(self, handle):
        self.collected.append(handle)
        return self.payloads[int(handle[1:])]


class ReviewerAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = load_module()

    def setUp(self):
        self.plan = self.rp.build_reviewer_plan(ROOT, "run", {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]})

    def payloads(self):
        return [{"reviewer_id": item.reviewer_id, "scope_id": item.scope_id, "verdict": "PASS", "findings": [], "evidence": ["src/a.py"], "status": "complete"} for item in self.plan]

    def refs(self):
        return {"requirements": "R1", "design": "D1", "steering": "read-only", "scope": "src/a.py"}

    def test_claude_uses_one_parallel_batch_and_same_plan(self):
        fake = FakeClaude(self.payloads())
        result = self.rp.dispatch_claude_panel(self.plan, fake, "x", self.refs())
        self.assertTrue(result.passed)
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(len(fake.requests[0]), len(self.plan))

    def test_codex_spawns_waits_collects_and_binds_runtime_identity(self):
        fake = FakeCodex(self.payloads())
        result = self.rp.dispatch_codex_panel(self.plan, fake, "x", ROOT, self.refs())
        self.assertTrue(result.passed)
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(len(fake.waited), len(self.plan))
        self.assertEqual(len(fake.collected), len(self.plan))
        self.assertTrue(all(request["sandbox"] == "read-only" for request in fake.requests[0]))

    def test_codex_mutation_fails_closed(self):
        fake = FakeCodex(self.payloads(), mutate=True)
        self.assertFalse(self.rp.dispatch_codex_panel(self.plan, fake, "x", ROOT, self.refs()).passed)

    def test_codex_self_report_cannot_route_a_result(self):
        payloads = self.payloads()
        payloads[0] = dict(payloads[0], reviewer_id="spoof")
        fake = FakeCodex(payloads)
        self.assertFalse(self.rp.dispatch_codex_panel(self.plan, fake, "x", ROOT, self.refs()).passed)


if __name__ == "__main__":
    unittest.main()
