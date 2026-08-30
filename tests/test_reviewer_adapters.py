from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from tests.test_reviewer_plan import load_module, ROOT


class FakeClaude:
    def __init__(self, payloads):
        self.payloads, self.requests = payloads, []

    def launch_batch(self, requests):
        self.requests.append(requests)
        return [{"invocation_id": f"agent-{i}", "planned_reviewer_id": payload["reviewer_id"],
                 "reviewer_id": payload["reviewer_id"], "payload": payload}
                for i, payload in enumerate(self.payloads)]


class ReviewerAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = load_module()

    def setUp(self):
        self.plan = self.rp.build_reviewer_plan(ROOT, "run", {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]})

    def payloads(self):
        return [{"reviewer_id": item.reviewer_id, "scope_id": item.scope_id, "lens": item.lens, "verdict": "PASS", "findings": [], "evidence": ["src/a.py"], "status": "complete"} for item in self.plan]

    def refs(self):
        return {"requirements": "R1", "design": "D1", "steering": "read-only", "scope": "src/a.py"}

    def test_claude_uses_one_parallel_batch_and_same_plan(self):
        fake = FakeClaude(self.payloads())
        result = self.rp.dispatch_claude_panel(self.plan, fake, "x", self.refs())
        self.assertTrue(result.passed)
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(len(fake.requests[0]), len(self.plan))

    def test_claude_accepts_reordered_trusted_invocation_results(self):
        fake = FakeClaude(list(reversed(self.payloads())))
        self.assertTrue(self.rp.dispatch_claude_panel(self.plan, fake, "x", self.refs()).passed)

    def test_claude_rejects_positional_or_duplicate_identity(self):
        class Positional(FakeClaude):
            def launch_batch(self, requests):
                self.requests.append(requests)
                return self.payloads
        self.assertFalse(self.rp.dispatch_claude_panel(self.plan, Positional(self.payloads()), "x", self.refs()).passed)
        duplicate = self.payloads()
        duplicate[-1] = dict(duplicate[-1], reviewer_id=duplicate[0]["reviewer_id"])
        self.assertFalse(self.rp.dispatch_claude_panel(self.plan, FakeClaude(duplicate), "x", self.refs()).passed)

    def test_claude_rejects_duplicate_invocation_handles(self):
        class DuplicateHandle(FakeClaude):
            def launch_batch(self, requests):
                self.requests.append(requests)
                return [{"invocation_id": "same", "planned_reviewer_id": payload["reviewer_id"],
                         "reviewer_id": payload["reviewer_id"], "payload": payload}
                        for payload in self.payloads]
        self.assertFalse(self.rp.dispatch_claude_panel(self.plan, DuplicateHandle(self.payloads()), "x", self.refs()).passed)

    def test_minimax_uses_the_same_claude_boundary(self):
        fake = FakeClaude(self.payloads())
        result = self.rp.dispatch_minimax_panel(self.plan, fake, "x", self.refs())
        self.assertTrue(result.passed)
        self.assertEqual(len(fake.requests), 1)

    def test_claude_legacy_file_is_preserved_without_changing_dispatch_skills(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = root / ".claude" / "agents" / "sdd-review-performance.md"
            agent.parent.mkdir(parents=True)
            source = "---\nname: sdd-review-performance\ndescription: Legacy\nmodel: sonnet\ntools: Read\n---\nCheck performance.\n"
            agent.write_text(source, encoding="utf-8")
            scope = {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]}
            plan = self.rp.build_reviewer_plan(root, "run", scope)
            fake = FakeClaude([dict(payload, evidence=["src/a.py"]) for payload in [
                {"reviewer_id": item.reviewer_id, "scope_id": item.scope_id, "lens": item.lens,
                 "verdict": "PASS", "findings": [], "evidence": ["src/a.py"], "status": "complete"}
                for item in plan]])
            self.assertTrue(self.rp.dispatch_claude_panel(plan, fake, "x", self.refs()).passed)
            self.assertEqual(agent.read_text(encoding="utf-8"), source)
            project_request = next(request for request in fake.requests[0] if "sdd-review-performance" in request)
            self.assertIn("Check performance.", project_request)
            self.assertNotIn("model: sonnet", project_request)
            self.assertNotIn("tools: Read", project_request)

    def test_codex_legacy_handoff_keeps_body_and_scope_without_claude_capabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = root / ".claude" / "agents" / "sdd-review-performance.md"
            agent.parent.mkdir(parents=True)
            agent.write_text(
                "---\nname: sdd-review-performance\ndescription: Legacy\nmodel: sonnet\ntools: Read\n---\nCheck performance.\n",
                encoding="utf-8",
            )
            scope = {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]}
            plan = self.rp.build_reviewer_plan(root, "run", scope)
            handoff = self.rp.build_codex_handoff(plan, "x", ROOT, self.refs())
            request = next(item for item in handoff["requests"] if item["reviewer_id"] == "sdd-review-performance")
            self.assertIn("Check performance.", request["prompt"])
            self.assertEqual(request["scope_id"], "run:x")
            self.assertEqual(request["sandbox"], "read-only")
            self.assertNotIn("model: sonnet", request["prompt"])
            self.assertNotIn("tools: Read", request["prompt"])

    def codex_handoff(self, payloads=None):
        handoff = self.rp.build_codex_handoff(self.plan, "x", ROOT, self.refs())
        payloads = payloads or self.payloads()
        handoff["bindings"] = {f"h{i}": item.reviewer_id for i, item in enumerate(self.plan)}
        handoff["waited"] = list(handoff["bindings"])
        handoff["results"] = [{"handle": f"h{i}", "payload": payload} for i, payload in enumerate(payloads)]
        return handoff

    def test_codex_handoff_is_prepared_without_runtime_spawn(self):
        handoff = self.rp.build_codex_handoff(self.plan, "x", ROOT, self.refs())
        self.assertTrue(handoff["parallel"])
        self.assertEqual(handoff["expected"], [item.reviewer_id for item in self.plan])
        self.assertNotIn("spawn_batch", self.rp.build_codex_handoff.__code__.co_names)

    def test_codex_rejects_non_worktree_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                self.rp.build_codex_handoff(self.plan, "x", Path(directory), self.refs())

    def test_codex_requires_mutation_snapshots(self):
        handoff = self.codex_handoff()
        self.assertFalse(self.rp.dispatch_codex_panel(self.plan, handoff, "x", ROOT, self.refs()).passed)

    def test_codex_handoff_validates_trusted_bindings_and_collection(self):
        result = self.rp.dispatch_codex_panel(self.plan, self.codex_handoff(), "x", ROOT, self.refs(), baseline="clean", final_snapshot="clean")
        self.assertTrue(result.passed)
        self.assertTrue(all(request["sandbox"] == "read-only" for request in self.rp.build_codex_handoff(self.plan, "x", ROOT, self.refs())["requests"]))

    def test_codex_mutation_fails_closed(self):
        handoff = self.codex_handoff()
        self.assertFalse(self.rp.validate_codex_handoff(self.plan, handoff, worktree=ROOT, baseline="a", final_snapshot="b").passed)

    def test_codex_self_report_cannot_route_a_result(self):
        payloads = self.payloads()
        payloads[0] = dict(payloads[0], reviewer_id="spoof")
        self.assertFalse(self.rp.dispatch_codex_panel(self.plan, self.codex_handoff(payloads), "x", ROOT, self.refs(), baseline="clean", final_snapshot="clean").passed)

    def test_codex_incomplete_collection_is_unavailable(self):
        handoff = self.codex_handoff()
        handoff["results"] = handoff["results"][:-1]
        self.assertFalse(self.rp.dispatch_codex_panel(self.plan, handoff, "x", ROOT, self.refs(), baseline="clean", final_snapshot="clean").passed)

    def test_codex_requires_all_waits_and_rejects_extra_handles(self):
        handoff = self.codex_handoff()
        handoff["waited"] = handoff["waited"][:-1]
        self.assertFalse(self.rp.dispatch_codex_panel(self.plan, handoff, "x", ROOT, self.refs(), baseline="clean", final_snapshot="clean").passed)
        handoff = self.codex_handoff()
        handoff["results"].append({"handle": "unexpected", "payload": self.payloads()[0]})
        self.assertFalse(self.rp.dispatch_codex_panel(self.plan, handoff, "x", ROOT, self.refs()).passed)


if __name__ == "__main__":
    unittest.main()
