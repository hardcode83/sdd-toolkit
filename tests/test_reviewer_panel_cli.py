from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from tests.test_reviewer_plan import ROOT, load_module


class ReviewerPanelCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = load_module()
        cls.command = [sys.executable, str(ROOT / "scripts" / "reviewer_panel.py")]

    def scope(self, phase="run"):
        return {"feature": "x", "scope_id": f"{phase}:x", "files": ["src/a.py"]}

    def results(self, phase="run"):
        plan = self.rp.build_reviewer_plan(ROOT, phase, self.scope(phase))
        return [{"invocation_id": f"agent-{i}", "planned_reviewer_id": item.reviewer_id,
                 "reviewer_id": item.reviewer_id,
                 "payload": {"reviewer_id": item.reviewer_id, "scope_id": item.scope_id,
                             "lens": item.lens, "verdict": "PASS", "findings": [],
                             "evidence": ["src/a.py"], "status": "complete"}}
                for i, item in enumerate(plan)]

    def invoke(self, phase, results):
        # Phase run certifies one section, so the gate demands which (ADR 0008).
        section = ["--section", "1"] if phase == "run" else []
        return subprocess.run(self.command + ["--root", str(ROOT), "--phase", phase, "--feature", "x", "--scope", json.dumps(self.scope(phase)), "--results", json.dumps(results), *section], capture_output=True, text=True)

    def test_run_review_auto_gate_passes_only_with_complete_results(self):
        for phase in ("run", "review", "auto"):
            with self.subTest(phase=phase):
                self.assertEqual(self.invoke(phase, self.results(phase)).returncode, 0)
                self.assertEqual(self.invoke(phase, self.results(phase)[:-1]).returncode, 1)
                self.assertEqual(self.invoke(phase, self.results(phase) + self.results(phase)[:1]).returncode, 1)

    def test_solo_cli_cannot_pass(self):
        result = subprocess.run(self.command + ["--root", str(ROOT), "--phase", "run", "--feature", "x", "--scope", json.dumps(self.scope()), "--results", "[]", "--solo", "--section", "1"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)

    def test_cli_rejects_unassociated_self_labeled_results(self):
        raw = self.results()
        result = self.invoke("run", [entry["payload"] for entry in raw])
        self.assertEqual(result.returncode, 1)

    def test_cli_fails_closed_on_swapped_self_declared_identity(self):
        # Regression: two reviewers (e.g. sdd-architect and sdd-security) return
        # JSON whose self-declared `reviewer_id`/`lens` are swapped with each
        # other. The trusted `planned_reviewer_id` (which Agent call this is)
        # still names the right slots, so the gate must fail closed on exactly
        # those two reviewers instead of crashing the whole collection or
        # silently accepting the cross-wired verdicts.
        raw = self.results("review")
        a, b = raw[0], raw[1]
        a["payload"], b["payload"] = dict(b["payload"]), dict(a["payload"])
        result = self.invoke("review", raw)
        self.assertEqual(result.returncode, 1)
        output = json.loads(result.stdout)
        self.assertEqual(output["gate"], "FAIL")
        self.assertTrue(any(a["planned_reviewer_id"] in err for err in output["errors"]))
        self.assertTrue(any(b["planned_reviewer_id"] in err for err in output["errors"]))


if __name__ == "__main__":
    unittest.main()
