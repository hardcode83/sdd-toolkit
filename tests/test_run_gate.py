from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import sdd_session  # noqa: E402
from test_reviewer_plan import load_module  # noqa: E402
from validate_toolkit import run_doctor  # noqa: E402

FEATURE = "example"
PANEL = [sys.executable, str(ROOT / "scripts" / "reviewer_panel.py")]
TASKS = (
    "# Tasks\n\n"
    "## 1. Domain <!-- hard -->\n\n- [x] 1.1 Done [R1]\n\n"
    "## 2. API\n\n- [x] 2.1 Done [R1]\n\n"
    "## 3. Verification\n\n- [ ] 3.1 Suite\n"
)


class GateFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.change = self.root / "sdd" / "changes" / FEATURE
        self.change.mkdir(parents=True)
        (self.root / "sdd" / "project.md").write_text("# Project\n", encoding="utf-8")
        (self.change / "proposal.md").write_text("# Proposal\n\n## Requirements\n\n### R1 — Example\n", encoding="utf-8")
        (self.change / "tasks.md").write_text(TASKS, encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
        self.git("init", "-q", "-b", "sdd/example")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "SDD Test")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "fixture")
        self.rp = load_module()

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True)

    def scope(self, section: int = 1) -> dict:
        return {"feature": FEATURE, "scope_id": f"run:{FEATURE}:{section}", "files": ["src/a.py"]}

    def envelopes(self, section: int = 1, fail: str | None = None) -> list[dict]:
        plan = self.rp.build_reviewer_plan(self.root, "run", self.scope(section))
        out = []
        for item in plan:
            verdict = "FAIL" if item.reviewer_id == fail else "PASS"
            out.append({"invocation_id": f"agent-{item.reviewer_id}", "planned_reviewer_id": item.reviewer_id,
                        "reviewer_id": item.reviewer_id,
                        "payload": {"reviewer_id": item.reviewer_id, "scope_id": item.scope_id, "lens": item.lens,
                                    "verdict": verdict, "findings": [] if verdict == "PASS" else [{"what": "x"}],
                                    "evidence": ["src/a.py"] if verdict == "PASS" else [], "status": "complete"}})
        return out

    def gate(self, *extra: str, section: int = 1, envelopes: list[dict] | None = None) -> subprocess.CompletedProcess[str]:
        args = PANEL + ["--root", str(self.root), "--phase", "run", "--feature", FEATURE,
                        "--scope", json.dumps(self.scope(section))]
        if envelopes is not None:
            args += ["--results", json.dumps(envelopes)]
        return subprocess.run(args + list(extra), capture_output=True, text=True)

    def tasks(self) -> str:
        return (self.change / "tasks.md").read_text(encoding="utf-8")


class PlanTests(GateFixture):
    """The orchestrator of the first dense auto run grepped the gate's source to
    learn the JSON shapes. `--plan` says them."""

    def test_plan_prints_the_reviewers_and_an_example_results_list(self) -> None:
        result = self.gate("--plan")
        self.assertEqual(0, result.returncode, result.stdout)
        plan = json.loads(result.stdout)
        ids = {r["reviewer_id"] for r in plan["reviewers"]}
        self.assertTrue({"sdd-architect", "sdd-security", "sdd-qa"} <= ids)
        example = plan["example_results"]
        self.assertEqual(len(plan["launch"]), len(example))
        self.assertEqual(f"run:{FEATURE}:1", example[0]["payload"]["scope_id"])
        self.assertIn("tool_use id", example[0]["invocation_id"])
        # Nothing evaluated, nothing written.
        self.assertNotIn("panel:", self.tasks())

    def test_results_are_required_unless_planning(self) -> None:
        result = self.gate()
        self.assertEqual(1, result.returncode)
        self.assertIn("--results is required", result.stdout)

    def test_help_shows_the_shapes(self) -> None:
        result = subprocess.run(PANEL + ["--help"], capture_output=True, text=True)
        self.assertIn('"scope_id": "run:<f>:<N>"', result.stdout)
        self.assertIn("--section N", result.stdout)


class SectionReceiptTests(GateFixture):
    """The gate is the only writer of `panel: PASS` (ADR 0008)."""

    def test_run_phase_requires_a_section(self) -> None:
        result = self.gate(envelopes=self.envelopes())
        self.assertEqual(1, result.returncode)
        self.assertIn("--section N is required", result.stdout)

    def test_a_passing_section_is_annotated_by_the_gate_with_its_receipt_id(self) -> None:
        result = self.gate("--section", "1", envelopes=self.envelopes(1))
        self.assertEqual(0, result.returncode, result.stdout)
        output = json.loads(result.stdout)
        self.assertTrue(output["annotated"])
        self.assertTrue(output["receipt"].endswith(f"sdd/receipts/{FEATURE}-run-1.json"))
        heading = next(l for l in self.tasks().splitlines() if l.startswith("## 1."))
        self.assertIn("<!-- hard -->", heading, "other markers survive")
        self.assertIn(f"receipt:{output['receipt_id']}", heading)
        self.assertIn("panel: PASS", heading)
        receipt = json.loads(Path(output["receipt"]).read_text(encoding="utf-8"))
        self.assertEqual((1, "PASS", output["receipt_id"]), (receipt["section"], receipt["gate"], receipt["id"]))
        # The tree carries only the annotation; the receipt lives outside it.
        self.assertEqual(["M sdd/changes/example/tasks.md"], [l.strip() for l in self.git("status", "--porcelain").stdout.splitlines()])

    def test_a_failing_section_gets_a_receipt_but_no_annotation(self) -> None:
        result = self.gate("--section", "2", section=2, envelopes=self.envelopes(2, fail="sdd-qa"))
        self.assertEqual(1, result.returncode)
        output = json.loads(result.stdout)
        self.assertIn("annotated", output, result.stdout)
        self.assertFalse(output["annotated"])
        self.assertIsNotNone(output["receipt"])
        self.assertNotIn("panel:", next(l for l in self.tasks().splitlines() if l.startswith("## 2.")))

    def test_re_running_replaces_the_marker_instead_of_stacking(self) -> None:
        self.gate("--section", "1", envelopes=self.envelopes(1))
        self.gate("--section", "1", envelopes=self.envelopes(1))
        heading = next(l for l in self.tasks().splitlines() if l.startswith("## 1."))
        self.assertEqual(1, heading.count("panel:"))


class UnverifiedAnnotationTests(GateFixture):
    def diagnose(self) -> list[str]:
        return [l for l in run_doctor(self.root).stdout.splitlines() if "SDD032" in l]

    def test_a_hand_written_pass_is_reported(self) -> None:
        text = self.tasks().replace("## 2. API", "## 2. API <!-- panel: PASS 2026-09-06 -->")
        (self.change / "tasks.md").write_text(text, encoding="utf-8")
        reported = self.diagnose()
        self.assertEqual(1, len(reported), reported)
        self.assertIn("no `receipt:` id", reported[0])

    def test_a_gate_written_pass_is_clean(self) -> None:
        self.assertEqual(0, self.gate("--section", "1", envelopes=self.envelopes(1)).returncode)
        self.assertEqual([], self.diagnose())

    def test_a_forged_receipt_id_is_reported(self) -> None:
        text = self.tasks().replace("## 2. API", "## 2. API <!-- panel: PASS 2026-09-06 receipt:deadbeef -->")
        (self.change / "tasks.md").write_text(text, encoding="utf-8")
        reported = self.diagnose()
        self.assertEqual(1, len(reported), reported)
        self.assertIn("no receipt for section 2", reported[0])


class PluginVersionDriftTests(GateFixture):
    def test_check_notes_when_the_session_runs_an_older_plugin_than_installed(self) -> None:
        registry = self.root / "installed.json"
        registry.write_text(json.dumps({"plugins": {"sdd@sdd-toolkit": [
            {"projectPath": str(self.root), "version": "0.51.0"}]}}), encoding="utf-8")
        env = {"CLAUDE_PLUGIN_ROOT": "/x/.claude/plugins/cache/sdd-toolkit/sdd/0.44.0", sdd_session.INSTALLED_PLUGINS_ENV: str(registry)}
        previous = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            report = sdd_session.check(self.root, FEATURE)
            self.assertEqual(("0.44.0", "0.51.0"), (report["plugin_version"], report["installed_plugin_version"]))
            rendered = sdd_session.render_check(report)
            self.assertIn("runs sdd-toolkit 0.44.0 but 0.51.0 is installed", rendered)
            os.environ["CLAUDE_PLUGIN_ROOT"] = "/x/.claude/plugins/cache/sdd-toolkit/sdd/0.51.0"
            self.assertNotIn("is installed", sdd_session.render_check(sdd_session.check(self.root, FEATURE)))
        finally:
            for k, v in previous.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
