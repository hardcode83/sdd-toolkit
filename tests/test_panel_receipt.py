from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sdd_lifecycle import (  # noqa: E402
    LifecycleError,
    initial_state,
    mark_local_verified,
    panel_receipt,
    read_state,
    write_state,
)

FEATURE = "example"
PANEL = [sys.executable, str(ROOT / "scripts" / "reviewer_panel.py")]


class ReceiptFixture(unittest.TestCase):
    """A consumer project with one change, on its feature branch."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.change = self.root / "sdd" / "changes" / FEATURE
        self.change.mkdir(parents=True)
        (self.root / "sdd" / "project.md").write_text("# Project\n", encoding="utf-8")
        (self.change / "proposal.md").write_text("# Proposal\n\n## Requirements\n\n### R1 — Example\n", encoding="utf-8")
        (self.change / "tasks.md").write_text("# Tasks\n\n- [x] 1.1 Done [R1]\n", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
        write_state(self.change, initial_state())
        self.git("init", "-q", "-b", "sdd/example")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "SDD Test")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "fixture")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True)

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def commit(self, relative: str, content: str, message: str) -> str:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.git("add", relative)
        self.git("commit", "-q", "-m", message)
        return self.head()

    def scope(self) -> dict:
        return {"feature": FEATURE, "scope_id": f"review:{FEATURE}", "files": ["src/a.py"]}

    def envelope(self, reviewer_id: str, lens: str, verdict: str = "PASS") -> dict:
        payload = {"reviewer_id": reviewer_id, "scope_id": f"review:{FEATURE}", "lens": lens,
                   "verdict": verdict, "findings": [] if verdict == "PASS" else [{"what": "x"}],
                   "evidence": ["src/a.py"] if verdict == "PASS" else [], "status": "complete"}
        return {"invocation_id": f"agent-{reviewer_id}", "planned_reviewer_id": reviewer_id,
                "reviewer_id": reviewer_id, "payload": payload}

    CORE = (("sdd-architect", "architecture"), ("sdd-security", "security"), ("sdd-qa", "qa"))

    def lenses(self) -> dict[str, str]:
        # Lenses come from the toolkit's agent files; read them through the plan.
        sys.path.insert(0, str(ROOT / "tests"))
        from test_reviewer_plan import load_module  # noqa: E402

        plan = load_module().build_reviewer_plan(self.root, "review", self.scope())
        return {item.reviewer_id: item.lens for item in plan}

    def run_panel(self, envelopes: list[dict], *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            PANEL + ["--root", str(self.root), "--phase", "review", "--feature", FEATURE,
                     "--scope", json.dumps(self.scope()), "--results", json.dumps(envelopes), *extra],
            capture_output=True, text=True,
        )

    def all_pass(self) -> list[dict]:
        return [self.envelope(rid, lens) for rid, lens in self.lenses().items()]


class ReceiptWritingTests(ReceiptFixture):
    def test_a_passing_review_panel_leaves_a_receipt_at_head(self) -> None:
        result = self.run_panel(self.all_pass())
        self.assertEqual(0, result.returncode, result.stdout)
        output = json.loads(result.stdout)
        self.assertTrue(output["receipt"].endswith("sdd/receipts/example.json"))
        self.assertEqual("", self.git("status", "--porcelain").stdout.strip(), "the receipt must not dirty the tree")
        receipt = panel_receipt(self.root, FEATURE)
        self.assertEqual(("review", "PASS", self.head()), (receipt["phase"], receipt["gate"], receipt["sha"]))
        self.assertEqual({"sdd-architect", "sdd-security", "sdd-qa"}, {r["reviewer_id"] for r in receipt["reviewers"]})
        self.assertTrue(all("payload" in r for r in receipt["reviewers"]))

    def test_a_failing_panel_leaves_a_fail_receipt_without_payloads(self) -> None:
        lenses = self.lenses()
        envelopes = [self.envelope(rid, lens, "FAIL" if rid == "sdd-qa" else "PASS") for rid, lens in lenses.items()]
        result = self.run_panel(envelopes)
        self.assertEqual(1, result.returncode)
        receipt = panel_receipt(self.root, FEATURE)
        self.assertEqual("FAIL", receipt["gate"])
        qa = next(r for r in receipt["reviewers"] if r["reviewer_id"] == "sdd-qa")
        self.assertEqual("FAIL", qa["verdict"])
        self.assertNotIn("payload", qa)
        self.assertEqual([{"what": "x"}], qa["findings"], "FAIL findings travel in the receipt")
        self.assertEqual(1, qa["findings_count"])

    def test_no_receipt_is_written_for_a_change_that_does_not_exist(self) -> None:
        result = subprocess.run(
            PANEL + ["--root", str(self.root), "--phase", "review", "--feature", "ghost",
                     "--scope", json.dumps({**self.scope(), "feature": "ghost", "scope_id": "review:ghost"}),
                     "--results", "[]"],
            capture_output=True, text=True,
        )
        self.assertIsNone(json.loads(result.stdout).get("receipt"))


class CarryTests(ReceiptFixture):
    """A re-review after a documentation fix relaunches only what failed."""

    def test_pass_verdicts_are_carried_when_only_documents_changed(self) -> None:
        lenses = self.lenses()
        self.assertEqual(1, self.run_panel(
            [self.envelope(rid, lens, "FAIL" if rid == "sdd-qa" else "PASS") for rid, lens in lenses.items()]
        ).returncode)
        self.commit("sdd/changes/example/design.md", "# Design\n\nD1 fixed wording.\n", "docs fix")
        result = self.run_panel([self.envelope("sdd-qa", lenses["sdd-qa"])], "--carry")
        self.assertEqual(0, result.returncode, result.stdout)
        receipt = panel_receipt(self.root, FEATURE)
        self.assertEqual(("PASS", self.head()), (receipt["gate"], receipt["sha"]))

    def test_carry_is_refused_when_code_changed(self) -> None:
        lenses = self.lenses()
        self.run_panel(self.all_pass())
        self.commit("src/a.py", "print('b')\n", "code change")
        result = self.run_panel([self.envelope("sdd-qa", lenses["sdd-qa"])], "--carry")
        self.assertEqual(1, result.returncode)
        self.assertIn("carry refused: code changed", result.stdout)
        self.assertIn("src/a.py", result.stdout)

    def test_carry_needs_a_previous_receipt(self) -> None:
        result = self.run_panel([self.envelope("sdd-qa", self.lenses()["sdd-qa"])], "--carry")
        self.assertEqual(1, result.returncode)
        self.assertIn("no previous receipt", result.stdout)


class CertificationNeedsTheReceiptTests(ReceiptFixture):
    def test_mark_local_verified_refuses_without_a_receipt(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "No panel receipt"):
            mark_local_verified(self.root, FEATURE)

    def test_a_fail_receipt_does_not_certify(self) -> None:
        lenses = self.lenses()
        self.run_panel([self.envelope(rid, lens, "FAIL" if rid == "sdd-security" else "PASS") for rid, lens in lenses.items()])
        with self.assertRaisesRegex(LifecycleError, "records gate 'FAIL'"):
            mark_local_verified(self.root, FEATURE)

    def test_a_stale_receipt_does_not_certify_a_later_commit(self) -> None:
        self.run_panel(self.all_pass())
        self.commit("src/a.py", "print('c')\n", "later code")
        with self.assertRaisesRegex(LifecycleError, "code changed in between"):
            mark_local_verified(self.root, FEATURE)

    def test_a_docs_only_commit_after_the_receipt_still_certifies(self) -> None:
        """The review's own metrics commit moves HEAD; the panel judged code."""
        self.run_panel(self.all_pass())
        self.commit("sdd/changes/example/metrics.md", "| review | 1.0 |\n", "sdd(example): review metrics")
        self.assertIn("LOCAL_VERIFIED", mark_local_verified(self.root, FEATURE))

    def test_a_pass_receipt_at_head_certifies(self) -> None:
        self.run_panel(self.all_pass())
        message = mark_local_verified(self.root, FEATURE)
        self.assertIn("LOCAL_VERIFIED", message)
        self.assertEqual("LOCAL_VERIFIED", read_state(self.change)["state"])

    def test_the_receipt_command_says_whether_it_certifies_head(self) -> None:
        import io
        from contextlib import redirect_stdout
        import sdd_lifecycle

        def run() -> str:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                self.assertEqual(0, sdd_lifecycle.main(["--root", str(self.root), "receipt", FEATURE]))
            return buffer.getvalue().strip().splitlines()[-1]

        self.assertEqual("RECEIPT: STALE_OR_MISSING", run())
        self.run_panel(self.all_pass())
        self.assertEqual("RECEIPT: CERTIFIES_HEAD", run())
        self.commit("src/a.py", "print('d')\n", "later")
        self.assertEqual("RECEIPT: STALE_OR_MISSING", run())
        self.run_panel(self.all_pass())
        self.commit("docs/x.md", "# x\n", "docs")
        self.assertEqual("RECEIPT: CERTIFIES_HEAD", run(), "non-code changes do not stale the receipt")

    def test_the_receipt_is_shared_by_every_worktree_of_the_clone(self) -> None:
        linked = self.root / ".claude" / "worktrees" / "example"
        self.git("worktree", "add", "--detach", str(linked))
        self.run_panel(self.all_pass())
        self.assertIsNotNone(panel_receipt(linked, FEATURE))


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


class UiUxLensReceiptFixture(ReceiptFixture):
    """Task 5.3: the same fixture, plus the UI/UX lens present alongside the core panel."""

    def setUp(self) -> None:
        super().setUp()
        agents = self.root / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "sdd-review-ui-ux.md").write_text(UI_UX_AGENT, encoding="utf-8")
        frontend = self.root / "src" / "components" / "App.tsx"
        frontend.parent.mkdir(parents=True, exist_ok=True)
        frontend.write_text("export const App = () => null;\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "add ui-ux lens and a frontend file")

    def scope(self) -> dict:
        return {"feature": FEATURE, "scope_id": f"review:{FEATURE}",
                "files": ["src/a.py", "src/components/App.tsx"]}


class UiUxLensReceiptTests(UiUxLensReceiptFixture):
    def test_receipt_includes_the_lens_alongside_the_core_panel(self) -> None:
        lenses = self.lenses()
        self.assertIn("sdd-review-ui-ux", lenses)
        result = self.run_panel(self.all_pass())
        self.assertEqual(0, result.returncode, result.stdout)
        receipt = panel_receipt(self.root, FEATURE)
        self.assertEqual("PASS", receipt["gate"])
        self.assertEqual({"sdd-architect", "sdd-security", "sdd-qa", "sdd-review-ui-ux"},
                          {r["reviewer_id"] for r in receipt["reviewers"]})


class UiUxLensCarryTests(UiUxLensReceiptFixture):
    def test_carry_works_with_the_lens_present_alongside_the_core_panel(self) -> None:
        lenses = self.lenses()
        self.assertIn("sdd-review-ui-ux", lenses)
        self.assertEqual(1, self.run_panel(
            [self.envelope(rid, lens, "FAIL" if rid == "sdd-qa" else "PASS") for rid, lens in lenses.items()]
        ).returncode)
        self.commit("sdd/changes/example/design.md", "# Design\n\nD1 fixed wording.\n", "docs fix")
        result = self.run_panel([self.envelope("sdd-qa", lenses["sdd-qa"])], "--carry")
        self.assertEqual(0, result.returncode, result.stdout)
        receipt = panel_receipt(self.root, FEATURE)
        self.assertEqual(("PASS", self.head()), (receipt["gate"], receipt["sha"]))
        self.assertEqual({"sdd-architect", "sdd-security", "sdd-qa", "sdd-review-ui-ux"},
                          {r["reviewer_id"] for r in receipt["reviewers"]})


if __name__ == "__main__":
    unittest.main()
