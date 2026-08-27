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
        return [{"reviewer_id": item.reviewer_id, "scope_id": item.scope_id, "verdict": "PASS", "findings": [], "evidence": ["src/a.py"], "status": "complete"} for item in plan]

    def invoke(self, phase, results):
        return subprocess.run(self.command + ["--root", str(ROOT), "--phase", phase, "--feature", "x", "--scope", json.dumps(self.scope(phase)), "--results", json.dumps(results)], capture_output=True, text=True)

    def test_run_review_auto_gate_passes_only_with_complete_results(self):
        for phase in ("run", "review", "auto"):
            with self.subTest(phase=phase):
                self.assertEqual(self.invoke(phase, self.results(phase)).returncode, 0)
                self.assertEqual(self.invoke(phase, self.results(phase)[:-1]).returncode, 1)
                self.assertEqual(self.invoke(phase, self.results(phase) + self.results(phase)[:1]).returncode, 1)

    def test_solo_cli_cannot_pass(self):
        result = subprocess.run(self.command + ["--root", str(ROOT), "--phase", "run", "--feature", "x", "--scope", json.dumps(self.scope()), "--results", "[]", "--solo"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
