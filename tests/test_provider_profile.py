from __future__ import annotations

import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import provider_profile  # noqa: E402


class ProfileTests(unittest.TestCase):
    """R1: the env-derived profile for the Claude Code runtime. A capability
    that cannot be determined is "unknown", never a guessed provider value."""

    def test_base_url_is_none_when_unset(self) -> None:
        profile = provider_profile.read_claude_code_profile({})
        self.assertIsNone(profile["base_url"])

    def test_base_url_reads_anthropic_base_url(self) -> None:
        profile = provider_profile.read_claude_code_profile(
            {"ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic"}
        )
        self.assertEqual(profile["base_url"], "https://api.minimax.io/anthropic")

    def test_alias_map_holds_only_aliases_whose_variable_is_set(self) -> None:
        env = {
            "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "MiniMax-M3",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "MiniMax-M2",
        }
        profile = provider_profile.read_claude_code_profile(env)
        self.assertEqual(profile["alias_map"], {"sonnet": "MiniMax-M3", "opus": "MiniMax-M2"})

    def test_unset_alias_variables_stay_out_of_the_alias_map(self) -> None:
        profile = provider_profile.read_claude_code_profile(
            {"ANTHROPIC_BASE_URL": "https://api.kimi.com/anthropic"}
        )
        self.assertEqual(profile["alias_map"], {})

    def test_undeterminable_capabilities_are_unknown_not_guessed(self) -> None:
        """R1 criteria 3/4: nothing in the environment proves structured-output,
        effort, budget, or fallback support, so each is "unknown"."""
        profile = provider_profile.read_claude_code_profile(
            {
                "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": "MiniMax-M3",
            }
        )
        for field in ("structured_output", "effort", "budget_semantics", "fallback"):
            with self.subTest(field=field):
                self.assertEqual(profile[field], "unknown")

    def test_defaults_to_the_real_environment(self) -> None:
        profile = provider_profile.read_claude_code_profile()
        self.assertIn("base_url", profile)
        self.assertIn("alias_map", profile)


class AliasWarningsTests(unittest.TestCase):
    """R2: one actionable warning per unmapped alias behind a custom base URL."""

    BASE = {"ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic"}

    def test_no_base_url_means_no_warnings(self) -> None:
        self.assertEqual(provider_profile.alias_warnings(["sonnet", "opus"], {}), [])

    def test_one_warning_per_missing_alias_naming_the_exact_variable(self) -> None:
        warnings = provider_profile.alias_warnings(["sonnet", "opus"], dict(self.BASE))
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("ANTHROPIC_DEFAULT_SONNET_MODEL" in w for w in warnings))
        self.assertTrue(any("ANTHROPIC_DEFAULT_OPUS_MODEL" in w for w in warnings))
        for warning in warnings:
            self.assertIn("ANTHROPIC_BASE_URL is set but", warning)

    def test_a_mapped_alias_warns_nothing(self) -> None:
        env = {**self.BASE, "ANTHROPIC_DEFAULT_SONNET_MODEL": "MiniMax-M3"}
        self.assertEqual(provider_profile.alias_warnings(["sonnet"], env), [])

    def test_full_model_name_passes_through_with_no_warning(self) -> None:
        """R2 criterion 3: a full model ID needs no alias mapping."""
        self.assertEqual(provider_profile.alias_warnings(["MiniMax-M3"], dict(self.BASE)), [])


class CliTests(unittest.TestCase):
    def run_cli(self, argv: list[str], env: dict[str, str]) -> tuple[int, str]:
        buffer = io.StringIO()
        old = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        try:
            with redirect_stderr(buffer):
                code = provider_profile.main(argv)
        finally:
            os.environ.clear()
            os.environ.update(old)
        return code, buffer.getvalue()

    def test_exit_zero_when_everything_is_mapped(self) -> None:
        code, err = self.run_cli(
            ["check", "--aliases", "sonnet,opus"],
            {
                "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": "MiniMax-M3",
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "MiniMax-M2",
            },
        )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_exit_one_and_stderr_when_a_mapping_is_missing(self) -> None:
        code, err = self.run_cli(
            ["check", "--aliases", "sonnet,opus"],
            {"ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic"},
        )
        self.assertEqual(code, 1)
        self.assertIn("ANTHROPIC_DEFAULT_SONNET_MODEL", err)
        self.assertIn("ANTHROPIC_DEFAULT_OPUS_MODEL", err)

    def test_exit_zero_with_no_base_url_even_without_mappings(self) -> None:
        code, err = self.run_cli(["check", "--aliases", "sonnet,opus"], {})
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_repeated_flags_are_accepted(self) -> None:
        code, err = self.run_cli(
            ["check", "--aliases", "sonnet", "--aliases", "opus"],
            {"ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic"},
        )
        self.assertEqual(code, 1)
        self.assertIn("ANTHROPIC_DEFAULT_OPUS_MODEL", err)

    def test_cli_as_subprocess(self) -> None:
        """The documented invocation, end to end."""
        script = ROOT / "scripts" / "provider_profile.py"
        env = {
            "PATH": os.environ.get("PATH", ""),
            "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic",
        }
        missing = subprocess.run(
            [sys.executable, str(script), "check", "--aliases", "sonnet,opus"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(missing.returncode, 1)
        self.assertIn("ANTHROPIC_DEFAULT_SONNET_MODEL", missing.stderr)
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = "MiniMax-M3"
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = "MiniMax-M2"
        mapped = subprocess.run(
            [sys.executable, str(script), "check", "--aliases", "sonnet,opus"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(mapped.returncode, 0)


if __name__ == "__main__":
    unittest.main()
