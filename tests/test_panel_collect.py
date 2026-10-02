"""`reviewer_panel.py --collect`: the gate reads verdicts from the harness.

Measured 2026-09-06..10-02 over 3052 transcripts: the permission classifier of
Claude Code's auto mode refused 28 gate invocations (`[CI Bypass]`,
`[Self-Approval]`) — 27 inside the subagents of /sdd:review, /sdd:run and
/sdd:auto — because the orchestrator typed `"verdict":"PASS"` envelopes into
`--results` (heredocs to /tmp, lambdas, reading tool-results back). From the
outside that is an agent fabricating a CI pass, and once it really was: a
review fork wrote PASS for reviewers still running. With `--collect` the
orchestrator passes only the ids of its own `Agent` calls; identity is what
the harness recorded as launched, and the verdict is what the reviewer
delivered. Every shape below is the one Claude Code 2.1.287 writes (ADR 0009).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import panel_collect  # noqa: E402
from test_run_gate import FEATURE, PANEL, GateFixture  # noqa: E402

SESSION = "11111111-2222-3333-4444-555555555555"
LENSES = {"sdd-architect": "architecture", "sdd-security": "security", "sdd-qa": "qa"}


class Transcripts:
    """A fake `~/.claude/projects` with one session and its subagents."""

    def __init__(self, base: Path, session: str = SESSION, project: str = "-tmp-project") -> None:
        self.projects = base / "projects"
        self.session_dir = self.projects / project / session
        self.subagents = self.session_dir / "subagents"
        self.subagents.mkdir(parents=True, exist_ok=True)
        self.main = self.projects / project / f"{session}.jsonl"
        self.main.touch()
        self.counter = 0

    @staticmethod
    def append(path: Path, *rows: dict) -> None:
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def launch(self, agent_type: str, prompt: str, *, meta_type: str | None = None,
               parent: Path | None = None, parent_agent: str | None = None,
               background: bool = True, launch_result: bool = True) -> tuple[str, str]:
        """Record an Agent call in the parent and its subagent's meta; return (agentId, toolu id)."""
        self.counter += 1
        agent_id = f"a{self.counter:016x}"
        tool_use = f"toolu_01TEST{self.counter:08d}abcdef"
        parent = parent or self.main
        self.append(parent, {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_use, "name": "Agent",
             "input": {"description": "review", "subagent_type": agent_type, "prompt": prompt}}]}})
        meta = {"agentType": meta_type or agent_type, "toolUseId": tool_use, "spawnDepth": 1,
                "requestShape": "background" if background else "foreground"}
        if parent_agent:
            meta["parentAgentId"] = parent_agent
        (self.subagents / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
        self.append(self.subagents / f"agent-{agent_id}.jsonl",
                    {"type": "user", "agentId": agent_id, "message": {"role": "user", "content": prompt}})
        if launch_result and background:
            self.tool_result(parent, tool_use, "Async agent launched successfully.\nagentId: " + agent_id)
        return agent_id, tool_use

    def tool_result(self, path: Path, tool_use: str, text: str, *, is_error: bool = False) -> None:
        block = {"type": "tool_result", "tool_use_id": tool_use, "content": [{"type": "text", "text": text}]}
        if is_error:
            block["is_error"] = True
        self.append(path, {"type": "user", "message": {"role": "user", "content": [block]}})

    def hand_back(self, agent_id: str, message: str, *, delivered: bool = True) -> None:
        transcript = self.subagents / f"agent-{agent_id}.jsonl"
        self.counter += 1
        call = f"toolu_01HB{self.counter:010d}abcdef"
        self.append(transcript, {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call, "name": "SubagentHandback", "input": {"message": message}}]}})
        if delivered:
            self.tool_result(transcript, call, json.dumps({"success": True, "message": "Report delivered to your caller."}))


def payload(reviewer_id: str, scope_id: str, verdict: str = "PASS", **overrides) -> dict:
    body = {"reviewer_id": reviewer_id, "scope_id": scope_id, "lens": LENSES[reviewer_id],
            "verdict": verdict, "findings": [] if verdict == "PASS" else [{"what": "x", "referent": "R1"}],
            "evidence": ["src/a.py"] if verdict == "PASS" else [], "status": "complete"}
    body.update(overrides)
    return body


def fenced(body: dict) -> str:
    return "Review done.\n\n```json\n" + json.dumps(body, indent=2) + "\n```\n"


class CollectFixture(GateFixture):
    def setUp(self) -> None:
        super().setUp()
        self.tx = Transcripts(self.root / ".claude-home")
        self.scope_id = f"run:{FEATURE}:1"

    def prompt(self, reviewer_id: str, scope_id: str | None = None) -> str:
        return f"Review section 1 of {FEATURE}. Exact scope ID: {scope_id or self.scope_id}. Lens {LENSES[reviewer_id]}."

    def launch_panel(self, report=None, **launch) -> dict[str, str]:
        """Launch the three core reviewers; each hands back `report(rid)` (default: a fenced PASS)."""
        report = report or (lambda rid: fenced(payload(rid, self.scope_id)))
        ids = {}
        for rid in LENSES:
            agent_id, _ = self.tx.launch(f"sdd:{rid}", self.prompt(rid), **launch)
            text = report(rid)
            if text is not None:
                self.tx.hand_back(agent_id, text)
            ids[rid] = agent_id
        return ids

    def collect(self, invocations: dict, *extra: str, session: str | None = SESSION,
                section: int = 1) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CONFIG_DIR")}
        if session:
            env["CLAUDE_CODE_SESSION_ID"] = session
        args = PANEL + ["--root", str(self.root), "--phase", "run", "--feature", FEATURE,
                        "--section", str(section), "--scope", json.dumps(self.scope(section)),
                        "--collect", "--invocations", json.dumps(invocations),
                        "--transcripts", str(self.tx.projects), *extra]
        return subprocess.run(args, capture_output=True, text=True, env=env)

    def output(self, result: subprocess.CompletedProcess[str]) -> dict:
        return json.loads(result.stdout)

    def reason(self, result, reviewer_id: str) -> str:
        out = self.output(result)
        row = next(r for r in out["results"] if r["reviewer_id"] == reviewer_id)
        self.assertEqual("unavailable", row["status"], out)
        return row["reason"]


class HappyPathTests(CollectFixture):
    def test_three_reviewers_collected_from_the_transcripts_pass_and_annotate(self) -> None:
        result = self.collect(self.launch_panel())
        self.assertEqual(0, result.returncode, result.stdout)
        out = self.output(result)
        self.assertEqual("PASS", out["gate"])
        self.assertTrue(out["annotated"])
        self.assertEqual({"complete"}, {c["state"] for c in out["collection"]})
        self.assertIn(f"receipt:{out['receipt_id']}", next(l for l in self.tasks().splitlines() if l.startswith("## 1.")))

    def test_tool_use_ids_and_raw_json_reports_work_too(self) -> None:
        ids = {}
        for rid in LENSES:
            agent_id, tool_use = self.tx.launch(f"sdd:{rid}", self.prompt(rid), background=False)
            self.tx.hand_back(agent_id, json.dumps(payload(rid, self.scope_id)))
            ids[rid] = tool_use
        result = self.collect(ids)
        self.assertEqual(0, result.returncode, result.stdout)

    def test_a_harness_without_handback_returns_the_report_as_the_call_result(self) -> None:
        ids = {}
        for rid in LENSES:
            agent_id, tool_use = self.tx.launch(rid, self.prompt(rid), background=False)
            self.tx.tool_result(self.tx.main, tool_use, json.dumps(payload(rid, self.scope_id)))
            ids[rid] = agent_id
        self.assertEqual(0, self.collect(ids).returncode)

    def test_an_orchestrating_subagent_is_the_parent_transcript(self) -> None:
        fork, _ = self.tx.launch("general-purpose", "run /sdd:review", background=False)
        fork_transcript = self.tx.subagents / f"agent-{fork}.jsonl"
        ids = self.launch_panel(parent=fork_transcript, parent_agent=fork)
        self.assertEqual(0, self.collect(ids).returncode)

    def test_pass_with_findings_is_judged_exactly_as_the_legacy_path_judges_it(self) -> None:
        noted = lambda rid: fenced(payload(rid, self.scope_id, findings=[{"what": "minor", "referent": "R1"}]))  # noqa: E731
        collected = self.collect(self.launch_panel(noted))
        legacy = self.gate("--section", "1", envelopes=[
            {"invocation_id": rid, "planned_reviewer_id": rid,
             "payload": payload(rid, self.scope_id, findings=[{"what": "minor", "referent": "R1"}])} for rid in LENSES])
        self.assertEqual(legacy.returncode, collected.returncode)
        self.assertEqual(json.loads(legacy.stdout)["gate"], self.output(collected)["gate"])
        findings = {r["reviewer_id"]: r["findings"] for r in self.output(collected)["results"]}
        self.assertEqual([{"what": "minor", "referent": "R1"}], findings["sdd-qa"])

    def test_a_fail_verdict_is_collected_as_a_fail(self) -> None:
        verdicts = lambda rid: fenced(payload(rid, self.scope_id, "FAIL" if rid == "sdd-qa" else "PASS"))  # noqa: E731
        result = self.collect(self.launch_panel(verdicts))
        self.assertEqual(1, result.returncode)
        row = next(r for r in self.output(result)["results"] if r["reviewer_id"] == "sdd-qa")
        self.assertEqual(("FAIL", "complete"), (row["verdict"], row["status"]))
        self.assertNotIn("panel:", next(l for l in self.tasks().splitlines() if l.startswith("## 1.")))


class FailClosedTests(CollectFixture):
    def test_spoofed_identity_the_launched_type_is_not_the_planned_reviewer(self) -> None:
        ids = self.launch_panel()
        # The qa slot is fed an architect run that reports itself as sdd-qa.
        spoof, _ = self.tx.launch("sdd:sdd-architect", self.prompt("sdd-qa"))
        self.tx.hand_back(spoof, fenced(payload("sdd-qa", self.scope_id)))
        ids["sdd-qa"] = spoof
        result = self.collect(ids)
        self.assertEqual(1, result.returncode)
        self.assertIn("not the planned reviewer", self.reason(result, "sdd-qa"))

    def test_meta_and_call_must_agree_on_the_launched_type(self) -> None:
        ids = self.launch_panel()
        forged, _ = self.tx.launch("sdd:sdd-architect", self.prompt("sdd-qa"), meta_type="sdd:sdd-qa")
        self.tx.hand_back(forged, fenced(payload("sdd-qa", self.scope_id)))
        ids["sdd-qa"] = forged
        self.assertIn("not an Agent call launching", self.reason(self.collect(ids), "sdd-qa"))

    def test_a_doubled_plugin_prefix_is_not_the_reviewer(self) -> None:
        ids = self.launch_panel()
        odd, _ = self.tx.launch("sdd:sdd:sdd-qa", self.prompt("sdd-qa"))
        self.tx.hand_back(odd, fenced(payload("sdd-qa", self.scope_id)))
        ids["sdd-qa"] = odd
        self.assertEqual(1, self.collect(ids).returncode)

    def test_missing_report_is_pending_and_fails_closed(self) -> None:
        ids = self.launch_panel(lambda rid: None if rid == "sdd-qa" else fenced(payload(rid, self.scope_id)))
        result = self.collect(ids)
        self.assertEqual(1, result.returncode)
        self.assertIn("has not delivered its report", self.reason(result, "sdd-qa"))
        self.assertIn("never reconstruct the verdict by hand", self.reason(result, "sdd-qa"))
        states = {c["reviewer_id"]: c["state"] for c in self.output(result)["collection"]}
        self.assertEqual("pending", states["sdd-qa"])

    def test_an_undelivered_handback_is_not_a_report(self) -> None:
        ids = self.launch_panel(lambda rid: None if rid == "sdd-qa" else fenced(payload(rid, self.scope_id)))
        self.tx.hand_back(ids["sdd-qa"], fenced(payload("sdd-qa", self.scope_id)), delivered=False)
        self.assertIn("has not delivered", self.reason(self.collect(ids), "sdd-qa"))

    def test_a_missing_agent_call_in_the_parent_fails(self) -> None:
        ids = self.launch_panel()
        self.tx.main.write_text("", encoding="utf-8")
        result = self.collect(ids)
        self.assertEqual(1, result.returncode)
        self.assertIn("is not in its parent transcript", self.reason(result, "sdd-qa"))

    def test_malformed_json_fails(self) -> None:
        broken = lambda rid: ('```json\n{"reviewer_id": "sdd-qa", "verdict": "PASS",\n```' if rid == "sdd-qa"  # noqa: E731
                              else fenced(payload(rid, self.scope_id)))
        result = self.collect(self.launch_panel(broken))
        self.assertEqual(1, result.returncode)
        self.assertIn("no JSON result object", self.reason(result, "sdd-qa"))

    def test_prose_without_json_fails(self) -> None:
        prose = lambda rid: "Verdict: PASS, no findings." if rid == "sdd-qa" else fenced(payload(rid, self.scope_id))  # noqa: E731
        self.assertIn("no JSON result object", self.reason(self.collect(self.launch_panel(prose)), "sdd-qa"))

    def test_two_different_result_objects_are_ambiguous(self) -> None:
        two = lambda rid: (fenced(payload(rid, self.scope_id, "FAIL")) + fenced(payload(rid, self.scope_id))  # noqa: E731
                           if rid == "sdd-qa" else fenced(payload(rid, self.scope_id)))
        self.assertIn("more than one different", self.reason(self.collect(self.launch_panel(two)), "sdd-qa"))

    def test_two_different_delivered_reports_are_ambiguous(self) -> None:
        ids = self.launch_panel()
        self.tx.hand_back(ids["sdd-qa"], fenced(payload("sdd-qa", self.scope_id, "FAIL")))
        self.assertIn("more than one different report", self.reason(self.collect(ids), "sdd-qa"))

    def test_an_id_recorded_in_two_transcripts_is_ambiguous(self) -> None:
        ids = self.launch_panel()
        other = Transcripts(self.root / ".claude-home", session="99999999-2222-3333-4444-555555555555")
        meta = (self.tx.subagents / f"agent-{ids['sdd-qa']}.meta.json").read_text(encoding="utf-8")
        (other.subagents / f"agent-{ids['sdd-qa']}.meta.json").write_text(meta, encoding="utf-8")
        # Without a session id the gate searches every project, and finds two.
        result = self.collect(ids, session=None)
        self.assertEqual(1, result.returncode)
        self.assertIn("ambiguous", self.reason(result, "sdd-qa"))
        # With the session id the other session's record is out of reach.
        self.assertEqual(0, self.collect(ids).returncode)

    def test_an_error_or_interrupted_call_fails_even_with_a_report(self) -> None:
        for text, is_error in (("Agent type 'sdd:sdd-qa' failed", True), ("[Request interrupted by user for tool use]", False)):
            with self.subTest(text=text):
                tx = Transcripts(self.root / f".home-{is_error}")
                self.tx = tx
                ids = {}
                for rid in LENSES:
                    agent_id, tool_use = tx.launch(f"sdd:{rid}", self.prompt(rid), background=False)
                    tx.hand_back(agent_id, fenced(payload(rid, self.scope_id)))
                    if rid == "sdd-qa":
                        tx.tool_result(tx.main, tool_use, text, is_error=is_error)
                    ids[rid] = agent_id
                result = self.collect(ids)
                self.assertEqual(1, result.returncode)
                self.assertIn("error or interruption", self.reason(result, "sdd-qa"))

    def test_scope_mismatch_in_the_payload_fails(self) -> None:
        other = lambda rid: fenced(payload(rid, f"run:{FEATURE}:2" if rid == "sdd-qa" else self.scope_id))  # noqa: E731
        self.assertIn("scope mismatch", self.reason(self.collect(self.launch_panel(other)), "sdd-qa"))

    def test_a_reviewer_launched_for_another_scope_fails(self) -> None:
        ids = self.launch_panel()
        stale, _ = self.tx.launch("sdd:sdd-qa", self.prompt("sdd-qa", f"run:{FEATURE}:2"))
        self.tx.hand_back(stale, fenced(payload("sdd-qa", self.scope_id)))
        ids["sdd-qa"] = stale
        self.assertIn("launched for another scope", self.reason(self.collect(ids), "sdd-qa"))

    def test_an_unknown_id_fails_with_an_actionable_reason(self) -> None:
        ids = self.launch_panel()
        ids["sdd-qa"] = "a00000000000dead0"
        self.assertIn("agentId printed by that Agent call", self.reason(self.collect(ids), "sdd-qa"))

    def test_an_id_that_is_not_an_id_fails(self) -> None:
        ids = self.launch_panel()
        ids["sdd-qa"] = "../*"
        self.assertIn("neither an agentId", self.reason(self.collect(ids), "sdd-qa"))

    def test_a_reviewer_left_out_of_the_invocations_is_unavailable(self) -> None:
        ids = self.launch_panel()
        del ids["sdd-qa"]
        result = self.collect(ids)
        self.assertEqual(1, result.returncode)
        self.assertIn("no invocation id was passed", self.reason(result, "sdd-qa"))

    def test_command_level_errors(self) -> None:
        ids = self.launch_panel()
        cases = {
            "same invocation id": {**ids, "sdd-qa": ids["sdd-security"]},
            "names reviewers the plan does not": {**ids, "sdd-intruder": ids["sdd-qa"]},
        }
        for needle, invocations in cases.items():
            with self.subTest(needle=needle):
                result = self.collect(invocations)
                self.assertEqual(1, result.returncode)
                self.assertIn(needle, " ".join(self.output(result)["errors"]))
        both = self.collect(ids, "--results", "[]")
        self.assertIn("--collect excludes --results", both.stdout)

    def test_reviewers_of_different_orchestrators_are_not_one_panel(self) -> None:
        ids = self.launch_panel()
        fork, _ = self.tx.launch("general-purpose", "another fork", background=False)
        fork_transcript = self.tx.subagents / f"agent-{fork}.jsonl"
        foreign, _ = self.tx.launch("sdd:sdd-qa", self.prompt("sdd-qa"), parent=fork_transcript, parent_agent=fork)
        self.tx.hand_back(foreign, fenced(payload("sdd-qa", self.scope_id)))
        ids["sdd-qa"] = foreign
        result = self.collect(ids)
        self.assertEqual(1, result.returncode)
        self.assertIn("different orchestrators", " ".join(self.output(result)["errors"]))


class WaitTests(CollectFixture):
    def test_wait_polls_until_the_deadline_and_still_fails_closed(self) -> None:
        ids = self.launch_panel(lambda rid: None if rid == "sdd-qa" else fenced(payload(rid, self.scope_id)))
        scopes = {rid: self.scope_id for rid in LENSES}
        collected = panel_collect.collect(ids, scopes, root=self.tx.projects, session_id=SESSION, wait=0.4, poll=0.1)
        self.assertEqual("pending", collected["sdd-qa"].state)

    def test_a_report_that_arrives_while_waiting_is_collected(self) -> None:
        ids = self.launch_panel(lambda rid: None if rid == "sdd-qa" else fenced(payload(rid, self.scope_id)))
        scopes = {rid: self.scope_id for rid in LENSES}
        original = panel_collect.time.sleep

        def sleep_then_deliver(seconds: float) -> None:
            self.tx.hand_back(ids["sdd-qa"], fenced(payload("sdd-qa", self.scope_id)))
            panel_collect.time.sleep = original

        panel_collect.time.sleep = sleep_then_deliver
        self.addCleanup(setattr, panel_collect.time, "sleep", original)
        collected = panel_collect.collect(ids, scopes, root=self.tx.projects, session_id=SESSION, wait=30, poll=0.1)
        self.assertEqual("complete", collected["sdd-qa"].state)

    def test_wait_is_bounded(self) -> None:
        self.assertIn("--wait must be between", self.collect(self.launch_panel(), "--wait", "99999").stdout)


class PlanNoLongerPrefillsAPassTests(GateFixture):
    def test_plan_prints_the_collect_command_and_no_ready_made_pass(self) -> None:
        result = self.gate("--plan", "--section", "1")
        plan = json.loads(result.stdout)
        self.assertIn("--collect --invocations", plan["collect"]["command"])
        self.assertNotIn('"verdict"', plan["collect"]["command"])
        self.assertNotIn('"verdict": "PASS"', result.stdout)
        self.assertNotIn('"verdict":"PASS"', result.stdout)

    def test_the_legacy_example_pasted_as_is_cannot_pass(self) -> None:
        plan = json.loads(self.gate("--plan", "--section", "1").stdout)
        result = self.gate("--section", "1", envelopes=plan["example_results"])
        self.assertEqual(1, result.returncode)
        self.assertEqual({"unavailable"}, {r["status"] for r in json.loads(result.stdout)["results"]})


class ExtractionRuleTests(unittest.TestCase):
    def test_identical_repeats_are_one_payload_and_nested_objects_are_ignored(self) -> None:
        body = payload("sdd-qa", "run:x:1", findings=[{"what": "a"}])
        text = json.dumps(body) + "\n\n```json\n" + json.dumps(body) + "\n```"
        self.assertEqual((body, None), panel_collect.extract_payload(text))

    def test_an_object_missing_a_contract_key_is_not_a_candidate(self) -> None:
        body = payload("sdd-qa", "run:x:1")
        del body["status"]
        found, reason = panel_collect.extract_payload(json.dumps(body))
        self.assertIsNone(found)
        self.assertIn("status", reason)


class SkillsInstructCollectTests(unittest.TestCase):
    """The skills are where the denied commands came from: `G=...; python3 "$G"
    --results '[{..."verdict":"PASS"...}]'`. They now say one static command."""

    SKILLS = ("run", "review", "auto", "reviewer-panel")

    def read(self, name: str) -> str:
        return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")

    def test_every_panel_skill_names_collect_and_never_a_typed_verdict(self) -> None:
        for name in self.SKILLS:
            with self.subTest(skill=name):
                text = self.read(name)
                self.assertIn("--collect", text)
                self.assertNotIn('"verdict":"PASS"', text)
                self.assertNotIn('"verdict": "PASS"', text)
                self.assertNotIn("--results '[", text)
                self.assertNotIn('G="${CLAUDE_PLUGIN_ROOT}', text)

    def test_the_gate_commands_are_single_static_invocations(self) -> None:
        for name in ("run", "review"):
            with self.subTest(skill=name):
                text = self.read(name)
                self.assertIn("python3 ${CLAUDE_PLUGIN_ROOT}/scripts/reviewer_panel.py", text)
                self.assertIn("--wait 540", text)
                for forbidden in ("heredoc", "/tmp", "tool-results"):
                    self.assertIn(forbidden, text, "named as forbidden next to the command")


if __name__ == "__main__":
    unittest.main()
