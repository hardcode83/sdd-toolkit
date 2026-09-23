"""R4 regression pin: reviewer dispatch/orchestration incident pattern.

The historical incident (ADR 0007/0008): reviewer work returned outside the
caller-bound collection and sections were annotated `panel: PASS` by hand, so
nothing on disk certified anything. These tests pin both arms of the pattern
at the dispatch/orchestration level, end to end at the Python boundary:

- correct arm: one caller-bound envelope per planned reviewer (trusted
  `planned_reviewer_id` = the launched identity) -> panel PASS -> the
  `reviewer_panel.py` gate writes a receipt -> `ensure_panel_receipt` accepts;
- failure arm "background return": envelopes lacking trusted invocation
  identity -> `dispatch_claude_panel` fails closed, no PASS panel;
- failure arm "fork ended without gate": self-declared PASS with no receipt
  on disk -> `ensure_panel_receipt` raises and `mark-local-verified` is
  unreachable;
- the doctor's SDD032 check keeps flagging a hand-written `panel: PASS`
  annotation that the gate did not write.

Payload-level validation lives in test_panel_contract.py,
test_reviewer_results.py, and test_reviewer_adapters.py; this module covers
the orchestration path and its lifecycle consequence.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from sdd_lifecycle import (  # noqa: E402
    LifecycleError,
    ensure_panel_receipt,
    mark_local_verified,
    panel_receipt,
)
from test_reviewer_plan import load_module  # noqa: E402
from validate_toolkit import run_doctor  # noqa: E402

FEATURE = "example"
PANEL = [sys.executable, str(ROOT / "scripts" / "reviewer_panel.py")]
TASKS = (
    "# Tasks\n\n"
    "## 1. Dispatch <!-- hard -->\n\n- [x] 1.1 Done [R1]\n\n"
    "## 2. Gate\n\n- [ ] 2.1 Verify [R1]\n"
)
REFERENTS = {"requirements": "R1", "design": "D1", "steering": "read-only", "scope": "src/a.py"}


class CallerBoundLauncher:
    """Fake Claude launcher returning one caller-bound envelope per request.

    The trusted identity (`planned_reviewer_id`) is set by the caller from the
    subagent it launched for that slot — never read out of the reviewer's own
    output. Envelopes are returned in request order, shuffled by the tests
    where order matters.
    """

    def __init__(self, envelopes: list[dict]):
        self.envelopes, self.requests = envelopes, []

    def launch_batch(self, requests):
        self.requests.append(requests)
        return list(self.envelopes)


class DispatchFixture(unittest.TestCase):
    """A consumer project with one change, on its feature branch (git fixture)."""

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
        self.git("init", "-q", "-b", f"sdd/{FEATURE}")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "SDD Test")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "fixture")
        self.rp = load_module()

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True)

    def scope(self) -> dict:
        return {"feature": FEATURE, "scope_id": f"review:{FEATURE}", "files": ["src/a.py"]}

    def plan(self):
        return self.rp.build_reviewer_plan(self.root, "review", self.scope())

    def envelope(self, item, verdict: str = "PASS") -> dict:
        payload = {"reviewer_id": item.reviewer_id, "scope_id": item.scope_id, "lens": item.lens,
                   "verdict": verdict, "findings": [] if verdict == "PASS" else [{"what": "x"}],
                   "evidence": ["src/a.py"] if verdict == "PASS" else [], "status": "complete"}
        return {"invocation_id": f"agent-{item.reviewer_id}", "planned_reviewer_id": item.reviewer_id,
                "reviewer_id": item.reviewer_id, "payload": payload}

    def all_pass(self) -> list[dict]:
        return [self.envelope(item) for item in self.plan()]

    def run_gate(self, envelopes: list[dict], phase: str = "review", section: int | None = None) -> subprocess.CompletedProcess[str]:
        args = PANEL + ["--root", str(self.root), "--phase", phase, "--feature", FEATURE,
                        "--scope", json.dumps(self.scope()), "--results", json.dumps(envelopes)]
        if section is not None:
            args += ["--section", str(section)]
        return subprocess.run(args, capture_output=True, text=True)

    def tasks_text(self) -> str:
        return (self.change / "tasks.md").read_text(encoding="utf-8")


class CorrectArmTests(DispatchFixture):
    """R4 criterion 2, correct path: dispatch -> gate -> receipt -> certification."""

    def test_caller_bound_panel_passes_and_certifies(self) -> None:
        envelopes = self.all_pass()
        panel = self.rp.dispatch_claude_panel(self.plan(), CallerBoundLauncher(envelopes), FEATURE, REFERENTS)
        self.assertEqual("PASS", panel.gate, panel.errors)
        self.assertTrue(panel.passed)

        result = self.run_gate(envelopes)
        self.assertEqual(0, result.returncode, result.stdout)
        output = json.loads(result.stdout)
        self.assertEqual("PASS", output["gate"])
        self.assertIsNotNone(output["receipt"], "the gate must write a receipt for a PASS panel")

        receipt = panel_receipt(self.root, FEATURE)
        self.assertEqual(("review", "PASS", output["receipt_id"]),
                         (receipt["phase"], receipt["gate"], receipt["id"]))
        self.assertEqual({"sdd-architect", "sdd-security", "sdd-qa"},
                         {r["reviewer_id"] for r in receipt["reviewers"]})

        accepted = ensure_panel_receipt(self.change, self.root)
        self.assertEqual(receipt["id"], accepted["id"])
        self.assertEqual("PASS", accepted["gate"])

    def test_reordered_caller_bound_envelopes_still_pass_and_certify(self) -> None:
        envelopes = list(reversed(self.all_pass()))
        panel = self.rp.dispatch_claude_panel(self.plan(), CallerBoundLauncher(envelopes), FEATURE, REFERENTS)
        self.assertTrue(panel.passed, panel.errors)
        result = self.run_gate(envelopes)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual("PASS", ensure_panel_receipt(self.change, self.root)["gate"])


class BackgroundReturnFailureTests(DispatchFixture):
    """R4 criterion 2, failure path: reviewer work returned outside the
    caller-bound collection — envelopes with no trusted invocation identity."""

    def test_envelopes_without_trusted_identity_fail_closed(self) -> None:
        plan = self.plan()
        bare = [{"payload": envelope["payload"]} for envelope in self.all_pass()]
        panel = self.rp.dispatch_claude_panel(plan, CallerBoundLauncher(bare), FEATURE, REFERENTS)
        self.assertEqual("FAIL", panel.gate)
        self.assertFalse(panel.passed, "no trusted binding must never become a PASS panel")
        self.assertIn("Claude trusted invocation identity mismatch", " ".join(panel.errors))
        with self.assertRaises(PermissionError):
            self.rp.certification_capability(panel)

    def test_envelopes_without_invocation_id_fail_closed(self) -> None:
        plan = self.plan()
        stripped = []
        for envelope in self.all_pass():
            entry = dict(envelope)
            del entry["invocation_id"]
            del entry["planned_reviewer_id"]
            stripped.append(entry)
        panel = self.rp.dispatch_claude_panel(plan, CallerBoundLauncher(stripped), FEATURE, REFERENTS)
        self.assertEqual("FAIL", panel.gate)
        self.assertFalse(panel.passed)
        self.assertIn("Claude trusted invocation identity mismatch", " ".join(panel.errors))


class ForkEndedWithoutGateTests(DispatchFixture):
    """R4 criterion 2/3, failure path: self-declared PASS, gate never run."""

    def test_self_declared_pass_without_receipt_certifies_nothing(self) -> None:
        text = self.tasks_text().replace("## 2. Gate", "## 2. Gate <!-- panel: PASS 2026-09-23 -->")
        (self.change / "tasks.md").write_text(text, encoding="utf-8")
        self.assertIsNone(panel_receipt(self.root, FEATURE), "the gate never ran: no receipt on disk")

        with self.assertRaisesRegex(LifecycleError, "No panel receipt"):
            ensure_panel_receipt(self.change, self.root)
        # Certification is unreachable even once every other gate is green:
        # the self-declared PASS wrote no receipt, and the lifecycle reads
        # receipts, not annotations.
        text = self.tasks_text().replace("- [ ] 2.1", "- [x] 2.1")
        (self.change / "tasks.md").write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(LifecycleError, "No panel receipt"):
            mark_local_verified(self.root, FEATURE)

    def test_background_style_annotation_alone_cannot_produce_capability(self) -> None:
        panel = self.rp.PanelResult(self.plan(), [], "PASS", [])
        with self.assertRaises(PermissionError):
            self.rp.certification_capability(panel)


class HandWrittenPassDoctorTests(DispatchFixture):
    """R4: SDD032 keeps flagging the hand-written annotation symptom."""

    def diagnose(self) -> list[str]:
        return [line for line in run_doctor(self.root).stdout.splitlines() if "SDD032" in line]

    def test_hand_written_pass_without_receipt_is_flagged(self) -> None:
        text = self.tasks_text().replace("## 2. Gate", "## 2. Gate <!-- panel: PASS 2026-09-23 -->")
        (self.change / "tasks.md").write_text(text, encoding="utf-8")
        reported = self.diagnose()
        self.assertEqual(1, len(reported), reported)
        self.assertIn("no `receipt:` id", reported[0])

    def test_gate_written_pass_annotation_is_not_flagged(self) -> None:
        # Only the run-phase gate annotates a section heading (ADR 0008); the
        # review-phase gate certifies via the receipt alone.
        result = self.run_gate(self.all_pass(), phase="run", section=1)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn("receipt:", next(l for l in self.tasks_text().splitlines() if l.startswith("## 1.")))
        self.assertEqual([], self.diagnose())


if __name__ == "__main__":
    unittest.main()
