from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sdd_auto_outcome  # noqa: E402


def result(**overrides):
    """A `claude -p --output-format json` result with the fields the recipe reads."""
    base = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "terminal_reason": "completed",
        "session_id": "11111111-2222-3333-4444-555555555555",
        "total_cost_usd": 0.42,
        "num_turns": 7,
        "permission_denials": [],
        "result": "done",
    }
    base.update(overrides)
    return base


def outcome(kind="PASS", **overrides):
    obj = {"outcome": kind, "next_command": "/sdd:ship demo", "decisions": [], "summary": "ok"}
    obj.update(overrides)
    return obj


class RecipeTests(unittest.TestCase):
    """The recipe is what turned three dead-on-arrival auto runs into a session
    that can execute the toolkit's own scripts (ADR 0005)."""

    def test_recipe_uses_auto_permission_mode_without_prompts(self) -> None:
        command = sdd_auto_outcome.build_command("/sdd:review demo")
        self.assertEqual(command[:3], ["claude", "-p", "/sdd:review demo"])
        self.assertIn("--permission-mode", command)
        self.assertEqual(command[command.index("--permission-mode") + 1], "auto")
        self.assertEqual(command[command.index("--permission-prompts") + 1], "none")
        self.assertEqual(command[command.index("--output-format") + 1], "json")
        self.assertNotIn("acceptEdits", command)
        self.assertNotIn("--bare", command)

    def test_recipe_carries_the_outcome_schema_and_the_auto_notice(self) -> None:
        command = sdd_auto_outcome.build_command("/sdd:review demo")
        schema = json.loads(command[command.index("--json-schema") + 1])
        self.assertEqual(schema, sdd_auto_outcome.PHASE_OUTCOME_SCHEMA)
        self.assertEqual(set(schema["required"]), {"outcome", "next_command", "decisions", "summary"})
        self.assertEqual(schema["properties"]["outcome"]["enum"], ["PASS", "BLOCKED", "FAILED"])
        self.assertIn("never ask anything", command[command.index("--append-system-prompt") + 1])

    def test_haiku_is_refused_as_session_model(self) -> None:
        """Measured: with Haiku the session starts in Manual and denies everything."""
        with self.assertRaises(sdd_auto_outcome.RecipeError):
            sdd_auto_outcome.build_command("/sdd:status", model="haiku")
        with self.assertRaises(sdd_auto_outcome.RecipeError):
            sdd_auto_outcome.build_command("/sdd:status", model="claude-haiku-4-5")
        sdd_auto_outcome.build_command("/sdd:status", model="opus")

    def test_optional_limits_are_passed_through(self) -> None:
        command = sdd_auto_outcome.build_command(
            "/sdd:run demo", model="opus", effort="medium", max_budget_usd=12.5,
            max_turns=80, fallback_model="sonnet",
        )
        self.assertEqual(command[command.index("--max-budget-usd") + 1], "12.5")
        self.assertEqual(command[command.index("--max-turns") + 1], "80")
        self.assertEqual(command[command.index("--fallback-model") + 1], "sonnet")
        self.assertEqual(command[command.index("--effort") + 1], "medium")

    def test_provider_alias_warning_only_behind_a_custom_base_url(self) -> None:
        """MiniMax and gateways remap the aliases through ANTHROPIC_DEFAULT_*_MODEL;
        an unmapped alias would ask the provider for an Anthropic model ID."""
        self.assertEqual([], sdd_auto_outcome.provider_warnings("sonnet", {}))
        base = {"ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic"}
        self.assertEqual(1, len(sdd_auto_outcome.provider_warnings("sonnet", base)))
        mapped = {**base, "ANTHROPIC_DEFAULT_SONNET_MODEL": "MiniMax-M3"}
        self.assertEqual([], sdd_auto_outcome.provider_warnings("sonnet", mapped))
        self.assertEqual(1, len(sdd_auto_outcome.provider_warnings("opus", mapped)))
        # A full model ID is passed through: nothing to remap, nothing to warn about.
        self.assertEqual([], sdd_auto_outcome.provider_warnings("MiniMax-M3", base))

    def test_delegated_environment_marks_both_guards(self) -> None:
        env = sdd_auto_outcome.delegated_environment({"PATH": "/bin"})
        self.assertEqual(env["SDD_AUTO_DELEGATED"], "1")
        self.assertEqual(env["SDD_AUTO"], "1")
        self.assertEqual(env["PATH"], "/bin")


class ClassifyTests(unittest.TestCase):
    def test_pass_blocked_failed_follow_the_outcome_object(self) -> None:
        for kind in ("PASS", "BLOCKED", "FAILED"):
            with self.subTest(kind=kind):
                verdict = sdd_auto_outcome.classify(result(structured_output=outcome(kind)))
                self.assertEqual(verdict["kind"], kind)
                self.assertEqual(verdict["next_command"], "/sdd:ship demo")
                self.assertEqual(verdict["cost_usd"], 0.42)

    def test_permission_denials_win_over_a_claimed_pass(self) -> None:
        denial = {
            "tool_name": "Bash",
            "tool_use_id": "toolu_1",
            "tool_input": {"command": "python3 scripts/sdd_lifecycle.py --root . mark-ready demo"},
        }
        verdict = sdd_auto_outcome.classify(
            result(structured_output=outcome("PASS"), permission_denials=[denial])
        )
        self.assertEqual(verdict["kind"], "DENIED")
        self.assertEqual(
            verdict["denied_commands"],
            ["Bash: python3 scripts/sdd_lifecycle.py --root . mark-ready demo"],
        )
        self.assertIn("denied: Bash: python3", sdd_auto_outcome.format_verdict(verdict))

    def test_abnormal_end_is_an_error_to_retry(self) -> None:
        verdict = sdd_auto_outcome.classify(
            result(is_error=True, terminal_reason="api_error", result="Not logged in · Please run /login")
        )
        self.assertEqual(verdict["kind"], "ERROR")
        self.assertIn("Not logged in", verdict["reason"])
        budget = sdd_auto_outcome.classify(result(terminal_reason="max_budget_usd"))
        self.assertEqual(budget["kind"], "ERROR")

    def test_missing_outcome_object_is_incomplete(self) -> None:
        self.assertEqual(sdd_auto_outcome.classify(result())["kind"], "INCOMPLETE")
        self.assertEqual(sdd_auto_outcome.classify(None)["kind"], "INCOMPLETE")
        bad = sdd_auto_outcome.classify(result(structured_output={"outcome": "MAYBE"}))
        self.assertEqual(bad["kind"], "INCOMPLETE")

    def test_the_verdict_is_the_last_line(self) -> None:
        text = sdd_auto_outcome.format_verdict(
            sdd_auto_outcome.classify(result(structured_output=outcome("BLOCKED", decisions=[
                {"question": "Which storage?", "options": ["S3", "local"], "recommendation": "S3"}
            ])))
        )
        self.assertEqual(text.splitlines()[-1], "AUTO_OUTCOME: BLOCKED")
        self.assertIn("decision: Which storage?", text)
        self.assertIn("recommended: S3", text)

    def test_parse_result_tolerates_hook_noise_before_the_json(self) -> None:
        text = "hook says hi\n" + json.dumps(result(structured_output=outcome()))
        parsed = sdd_auto_outcome.parse_result(text)
        self.assertEqual(parsed["structured_output"]["outcome"], "PASS")
        self.assertIsNone(sdd_auto_outcome.parse_result(""))

    def test_exit_codes_distinguish_the_kinds(self) -> None:
        codes = {kind: sdd_auto_outcome.exit_code(kind) for kind in sdd_auto_outcome.KINDS}
        self.assertEqual(codes["PASS"], 0)
        self.assertEqual(len(set(codes.values())), 5)


class RunTests(unittest.TestCase):
    """`run` never raises for a missing or broken `claude`: that would turn a cost
    optimisation into something that aborts a run."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bin = Path(self.directory.name) / "bin"
        self.bin.mkdir()
        self.previous_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{self.previous_path}"
        self.addCleanup(os.environ.__setitem__, "PATH", self.previous_path)

    def fake_claude(self, body: str) -> None:
        script = self.bin / "claude"
        script.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)

    def test_missing_claude_is_unavailable(self) -> None:
        verdict = sdd_auto_outcome.run("/sdd:review demo", executable="claude-that-does-not-exist")
        self.assertEqual(verdict["kind"], "UNAVAILABLE")

    def test_run_reads_the_json_the_session_prints(self) -> None:
        payload = json.dumps(result(structured_output=outcome("PASS")))
        # The fake records its argv and env so the test can check the recipe
        # actually reached the executable.
        record = Path(self.directory.name) / "argv.txt"
        self.fake_claude(
            f"printf '%s\\n' \"$@\" > '{record}'\n"
            f"printf '%s\\n' \"$SDD_AUTO_DELEGATED/$SDD_AUTO\" >> '{record}'\n"
            f"cat <<'EOF'\n{payload}\nEOF"
        )
        verdict = sdd_auto_outcome.run("/sdd:review demo", cwd=Path(self.directory.name), model="opus")
        self.assertEqual(verdict["kind"], "PASS")
        recorded = record.read_text(encoding="utf-8").splitlines()
        self.assertIn("--permission-mode", recorded)
        self.assertEqual(recorded[recorded.index("--permission-mode") + 1], "auto")
        self.assertEqual(recorded[recorded.index("--model") + 1], "opus")
        self.assertEqual(recorded[-1], "1/1")

    def test_a_crashing_claude_is_unavailable_not_an_exception(self) -> None:
        self.fake_claude("echo 'boom' >&2; exit 7")
        verdict = sdd_auto_outcome.run("/sdd:review demo")
        self.assertEqual(verdict["kind"], "UNAVAILABLE")
        self.assertIn("exit 7", verdict["reason"])

    def test_cli_read_obeys_the_last_line_contract(self) -> None:
        payload = json.dumps(result(structured_output=outcome("BLOCKED")))
        file = Path(self.directory.name) / "result.json"
        file.write_text(payload, encoding="utf-8")
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = sdd_auto_outcome.main(["read", "--file", str(file)])
        self.assertEqual(code, 2)
        self.assertEqual(buffer.getvalue().strip().splitlines()[-1], "AUTO_OUTCOME: BLOCKED")

    def test_cli_schema_prints_valid_json(self) -> None:
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(sdd_auto_outcome.main(["schema"]), 0)
        self.assertEqual(json.loads(buffer.getvalue())["required"][0], "outcome")


if __name__ == "__main__":
    unittest.main()
