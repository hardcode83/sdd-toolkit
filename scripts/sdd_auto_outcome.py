#!/usr/bin/env python3
"""Headless delegation for `/sdd:auto`: one recipe, one way to read what came back.

`/sdd:auto` runs the phases it delegates in a fresh `claude -p` session so the
orchestrating conversation never inherits their context (shared rule 11). Until
v0.46 the skill spelled that command out in prose, with `--permission-mode
acceptEdits` — and every real run died in under two minutes on a permission
prompt for `python3 …/sdd_roadmap.py`, because `acceptEdits` approves file
edits, not shell commands. Measured on Claude Code 2.1.261 (ADR 0005):

  * `acceptEdits` and `dontAsk` deny any Bash that is not in an allow rule;
  * `--permission-mode auto` with **Haiku** silently starts in `default` and
    denies everything; with Sonnet or Opus it starts in `auto` and the
    classifier approves the toolkit's scripts, git and the project's tests;
  * `--permission-prompts none` removes `AskUserQuestion` from the session and
    denies, without waiting, anything that would have prompted;
  * `--json-schema` returns a validated `structured_output` object.

This module is the single home for that recipe (`run`), for the outcome object a
delegated phase must end with (`schema`), and for turning the JSON `claude -p`
prints into one verdict the skill can act on (`read`). The verdict is the LAST
line of stdout, `AUTO_OUTCOME: <kind>`, so a caller obeys the last line the way
it already does with `sdd_session.py check`:

  PASS         the phase finished and reports success; confirm it on disk
  BLOCKED      the phase wrote BLOCKED.md and stopped — adopt it, move on
  FAILED       the phase reports a failed verdict — block the feature
  DENIED       permission denials: nothing to decide, a rule is missing —
               `deferred` entry with the exact command(s), never retry blind
  ERROR        the session ended abnormally (API error, budget, max turns) —
               retry once, then `deferred`
  INCOMPLETE   the session ended but produced no outcome object — treat as
               FAILED unless STATE.md proves otherwise
  UNAVAILABLE  no `claude` on PATH or it could not start — run the phase
               inline and say so in the report (never abort the run)

Evidence still lives on disk: `STATE.md`, `BLOCKED.md` and the checkboxes in
`tasks.md` are the facts; the outcome object is the sub-session's summary of
them, and the skill re-reads the disk before believing a PASS.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

OUTCOMES = ("PASS", "BLOCKED", "FAILED")
KINDS = ("PASS", "BLOCKED", "FAILED", "DENIED", "ERROR", "INCOMPLETE", "UNAVAILABLE")

# Auto mode is not available for Haiku: the session falls back to Manual without
# a warning and, headless, denies every command. Measured, not assumed.
FORBIDDEN_SESSION_MODELS = ("haiku",)
DEFAULT_MODEL = "sonnet"

DELEGATED_ENV = "SDD_AUTO_DELEGATED"
AUTO_ENV = "SDD_AUTO"

AUTO_SYSTEM_PROMPT = (
    "This session was launched by /sdd:auto and runs unattended. Apply the gate "
    "conversions of the auto skill: never ask anything (there is nobody to "
    "answer), treat an existing proposal/design/tasks document as approved input, "
    "persist every pending item in BLOCKED.md per shared rule 5, and finish your "
    "final message with the outcome object the caller requested (outcome, "
    "next_command, decisions, summary)."
)

PHASE_OUTCOME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outcome", "next_command", "decisions", "summary"],
    "properties": {
        "outcome": {
            "type": "string",
            "enum": list(OUTCOMES),
            "description": (
                "PASS: the phase completed and its evidence is on disk. BLOCKED: "
                "a BLOCKED.md entry was written and the phase stopped. FAILED: "
                "the phase ran and its verdict is negative."
            ),
        },
        "next_command": {
            "type": "string",
            "description": "The exact command the caller should run next, or an empty string.",
        },
        "decisions": {
            "type": "array",
            "description": "Questions a human must answer; one per BLOCKED.md `decision` entry.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["question", "options", "recommendation"],
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "recommendation": {"type": "string"},
                },
            },
        },
        "summary": {
            "type": "string",
            "description": "At most ~10 lines for the human; no diffs, no logs.",
        },
    },
}


class RecipeError(Exception):
    """A recipe that would launch a session known not to work."""


def build_command(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    effort: str | None = None,
    max_budget_usd: float | None = None,
    max_turns: int | None = None,
    fallback_model: str | None = None,
    executable: str = "claude",
) -> list[str]:
    """The headless recipe, as an argv list (no shell quoting to get wrong)."""
    if not prompt.strip():
        raise RecipeError("the prompt is empty")
    for forbidden in FORBIDDEN_SESSION_MODELS:
        if forbidden in model.lower():
            raise RecipeError(
                f"{model!r} cannot be the session model of a headless auto run: "
                "auto permission mode is unavailable for it, the session silently "
                "starts in Manual and every command is denied. Use sonnet or opus."
            )
    command = [
        executable,
        "-p",
        prompt,
        "--permission-mode",
        "auto",
        "--permission-prompts",
        "none",
        "--model",
        model,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(PHASE_OUTCOME_SCHEMA, separators=(",", ":")),
        "--append-system-prompt",
        AUTO_SYSTEM_PROMPT,
    ]
    if effort:
        command += ["--effort", effort]
    if max_budget_usd is not None:
        command += ["--max-budget-usd", f"{max_budget_usd:g}"]
    if max_turns is not None:
        command += ["--max-turns", str(max_turns)]
    if fallback_model:
        command += ["--fallback-model", fallback_model]
    return command


def delegated_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a delegated session runs with.

    `SDD_AUTO_DELEGATED` is what stops a delegated run from delegating again;
    `SDD_AUTO` is what lets any phase skill know it runs unattended even though
    it was started as `/sdd:<phase>` and not as `/sdd:auto`.
    """
    env = dict(os.environ if base is None else base)
    env[DELEGATED_ENV] = "1"
    env[AUTO_ENV] = "1"
    return env


def classify(result: Any) -> dict[str, Any]:
    """Turn the JSON `claude -p --output-format json` prints into one verdict."""
    verdict: dict[str, Any] = {
        "kind": "INCOMPLETE",
        "outcome": None,
        "next_command": "",
        "decisions": [],
        "summary": "",
        "denied_commands": [],
        "session_id": None,
        "cost_usd": None,
        "num_turns": None,
        "reason": "",
    }
    if not isinstance(result, dict):
        verdict["reason"] = "the session printed no JSON result"
        return verdict

    verdict["session_id"] = result.get("session_id")
    verdict["cost_usd"] = result.get("total_cost_usd")
    verdict["num_turns"] = result.get("num_turns")

    denials = result.get("permission_denials") or []
    denied: list[str] = []
    for denial in denials:
        if not isinstance(denial, dict):
            continue
        tool = denial.get("tool_name") or "?"
        tool_input = denial.get("tool_input") or {}
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        denied.append(f"{tool}: {command}" if command else f"{tool}: {json.dumps(tool_input, sort_keys=True)}")
    verdict["denied_commands"] = denied

    structured = result.get("structured_output")
    if isinstance(structured, dict) and structured.get("outcome") in OUTCOMES:
        verdict["outcome"] = structured["outcome"]
        verdict["next_command"] = str(structured.get("next_command") or "")
        decisions = structured.get("decisions")
        verdict["decisions"] = decisions if isinstance(decisions, list) else []
        verdict["summary"] = str(structured.get("summary") or "")

    # Denials come first: a phase that was refused a command and still reports
    # PASS is describing work it could not have verified.
    if denied:
        verdict["kind"] = "DENIED"
        verdict["reason"] = (
            f"{len(denied)} permission denial(s): the session has no approval "
            "surface, so this is a missing allow rule, not a decision"
        )
        return verdict

    terminal = result.get("terminal_reason")
    if result.get("is_error") or (terminal not in (None, "completed")):
        verdict["kind"] = "ERROR"
        verdict["reason"] = f"terminal_reason={terminal!r}, is_error={bool(result.get('is_error'))}"
        text = result.get("result")
        if isinstance(text, str) and text.strip():
            verdict["reason"] += f": {text.strip().splitlines()[0][:160]}"
        return verdict

    if verdict["outcome"] is None:
        verdict["reason"] = "the session ended without the outcome object"
        return verdict

    verdict["kind"] = verdict["outcome"]
    return verdict


def format_verdict(verdict: dict[str, Any]) -> str:
    lines = []
    kind = verdict["kind"]
    if verdict.get("session_id"):
        lines.append(f"session: {verdict['session_id']}")
    if verdict.get("cost_usd") is not None:
        lines.append(f"cost_usd: {verdict['cost_usd']:.4f}  turns: {verdict.get('num_turns')}")
    if verdict.get("reason"):
        lines.append(f"reason: {verdict['reason']}")
    if verdict.get("next_command"):
        lines.append(f"next_command: {verdict['next_command']}")
    for decision in verdict.get("decisions") or []:
        if isinstance(decision, dict):
            lines.append(f"decision: {decision.get('question', '')}")
            for option in decision.get("options") or []:
                lines.append(f"  - {option}")
            if decision.get("recommendation"):
                lines.append(f"  recommended: {decision['recommendation']}")
    for command in verdict.get("denied_commands") or []:
        lines.append(f"denied: {command}")
    if verdict.get("summary"):
        lines.append("summary:")
        lines.extend(f"  {line}" for line in verdict["summary"].splitlines()[:12])
    lines.append(f"AUTO_OUTCOME: {kind}")
    return "\n".join(lines)


def exit_code(kind: str) -> int:
    return {
        "PASS": 0,
        "BLOCKED": 2,
        "FAILED": 2,
        "DENIED": 3,
        "ERROR": 4,
        "INCOMPLETE": 4,
        "UNAVAILABLE": 5,
    }[kind]


def parse_result(text: str) -> Any:
    """`claude -p --output-format json` prints one JSON object; be lenient about
    anything a hook printed before it."""
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def run(
    prompt: str,
    *,
    cwd: Path | None = None,
    model: str = DEFAULT_MODEL,
    effort: str | None = None,
    max_budget_usd: float | None = None,
    max_turns: int | None = None,
    fallback_model: str | None = None,
    timeout: float | None = None,
    executable: str = "claude",
) -> dict[str, Any]:
    """Launch the delegated session and return its verdict (never raises for a
    missing or failing `claude`: that is the UNAVAILABLE kind)."""
    if shutil.which(executable) is None:
        return {**classify(None), "kind": "UNAVAILABLE", "reason": f"{executable!r} is not on PATH"}
    command = build_command(
        prompt,
        model=model,
        effort=effort,
        max_budget_usd=max_budget_usd,
        max_turns=max_turns,
        fallback_model=fallback_model,
        executable=executable,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=delegated_environment(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**classify(None), "kind": "UNAVAILABLE", "reason": f"could not run {executable!r}: {exc}"}
    result = parse_result(completed.stdout)
    verdict = classify(result)
    if result is None:
        stderr = completed.stderr.strip().splitlines()
        verdict["kind"] = "UNAVAILABLE" if completed.returncode != 0 else "INCOMPLETE"
        verdict["reason"] = (
            f"exit {completed.returncode}, no JSON result"
            + (f": {stderr[-1][:160]}" if stderr else "")
        )
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("schema", help="print the phase outcome JSON schema")

    read = sub.add_parser("read", help="classify a `claude -p --output-format json` result")
    read.add_argument("--file", type=Path, help="result file (default: stdin)")
    read.add_argument("--json", action="store_true", help="print the verdict as JSON")

    launch = sub.add_parser("run", help="launch a delegated phase with the headless recipe")
    launch.add_argument("prompt", help='e.g. "/sdd:review <feature>. The base branch is main."')
    launch.add_argument("--cwd", type=Path, help="working directory of the delegated session")
    launch.add_argument("--model", default=DEFAULT_MODEL, help="session model (sonnet|opus; never haiku)")
    launch.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"))
    launch.add_argument("--max-budget-usd", type=float)
    launch.add_argument("--max-turns", type=int)
    launch.add_argument("--fallback-model")
    launch.add_argument("--timeout", type=float, help="seconds before giving up on the session")
    launch.add_argument("--json", action="store_true", help="print the verdict as JSON")
    launch.add_argument("--print-command", action="store_true", help="print the argv and exit")

    args = parser.parse_args(argv)

    if args.command == "schema":
        print(json.dumps(PHASE_OUTCOME_SCHEMA, indent=2))
        return 0

    if args.command == "read":
        text = args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read()
        verdict = classify(parse_result(text))
        print(json.dumps(verdict, indent=2) if args.json else format_verdict(verdict))
        return exit_code(verdict["kind"])

    try:
        if args.print_command:
            for part in build_command(
                args.prompt,
                model=args.model,
                effort=args.effort,
                max_budget_usd=args.max_budget_usd,
                max_turns=args.max_turns,
                fallback_model=args.fallback_model,
            ):
                print(part)
            return 0
        verdict = run(
            args.prompt,
            cwd=args.cwd,
            model=args.model,
            effort=args.effort,
            max_budget_usd=args.max_budget_usd,
            max_turns=args.max_turns,
            fallback_model=args.fallback_model,
            timeout=args.timeout,
        )
    except RecipeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(verdict, indent=2) if args.json else format_verdict(verdict))
    return exit_code(verdict["kind"])


if __name__ == "__main__":
    raise SystemExit(main())
