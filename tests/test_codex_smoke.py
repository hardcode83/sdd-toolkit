from __future__ import annotations

import os
import json
import subprocess
import unittest
from pathlib import Path

from tests.test_reviewer_plan import load_module


ROOT = Path(__file__).resolve().parents[1]


class NativeCodexSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = load_module()

    def _handoff(self):
        scope = {"feature": "smoke", "scope_id": "run:smoke", "files": ["src/a.py"]}
        plan = self.rp.build_reviewer_plan(ROOT, "run", scope)
        refs = {"requirements": "R1", "design": "D1", "steering": "read-only", "scope": "src/a.py"}
        handoff = self.rp.build_codex_handoff(plan, "smoke", ROOT, refs)
        payloads = [{"reviewer_id": item.reviewer_id, "scope_id": item.scope_id,
                     "lens": item.lens, "verdict": "PASS", "findings": [],
                     "evidence": ["src/a.py"], "status": "complete"} for item in plan]
        handoff["bindings"] = {f"native-{i}": item.reviewer_id for i, item in enumerate(plan)}
        handoff["waited"] = list(handoff["bindings"])
        handoff["results"] = [{"handle": f"native-{i}", "payload": payload}
                               for i, payload in enumerate(payloads)]
        return plan, handoff, refs

    def test_repository_owned_harness_contract_positive_and_missing_reviewer_negative(self):
        """Layer B: deterministic contract evidence, not native execution."""
        plan, handoff, refs = self._handoff()
        self.assertEqual([item.reviewer_id for item in plan[:3]], list(self.rp.MANDATORY_CORE))
        positive = self.rp.dispatch_codex_panel(plan, handoff, "smoke", ROOT, refs)
        self.assertTrue(positive.passed, positive.errors)
        handoff["results"] = handoff["results"][:-1]
        negative = self.rp.dispatch_codex_panel(plan, handoff, "smoke", ROOT, refs)
        self.assertFalse(negative.passed)

    @unittest.skipUnless(os.environ.get("SDD_NATIVE_CODEX_SMOKE_CMD"), "opt-in native Codex smoke")
    def test_native_smoke_is_explicitly_opt_in(self):
        # Layer C is owned by the top-level Codex harness. The command must emit
        # the repository-owned JSON protocol; Python never spawns native children.
        completed = subprocess.run(os.environ["SDD_NATIVE_CODEX_SMOKE_CMD"], shell=True,
                                   check=False, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0)
        output = completed.stdout
        try:
            report = json.loads(output)
        except (TypeError, json.JSONDecodeError) as exc:
            self.fail(f"native smoke must emit repository-owned JSON: {exc}")
        self.assertEqual(report.get("expected"), list(self.rp.MANDATORY_CORE))
        self.assertEqual(report.get("positive"), "PASS")
        self.assertEqual(report.get("negative"), "FAIL")
        self.assertEqual(report.get("association"), "trusted-handle")
        self.assertTrue(report.get("parallel"))
        self.assertTrue(report.get("waited"))
        self.assertTrue(report.get("collected"))
        self.assertTrue(report.get("worktree_unchanged"))


if __name__ == "__main__":
    unittest.main()
