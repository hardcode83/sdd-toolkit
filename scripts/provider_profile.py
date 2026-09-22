#!/usr/bin/env python3
"""Provider capability profile and alias preflight for the Claude Code runtime.

The toolkit names models by alias (haiku/sonnet/opus/fable) so the environment
can remap them per provider. Behind `ANTHROPIC_BASE_URL` (Kimi, MiniMax, a
gateway, Bedrock) an alias resolves to whatever `ANTHROPIC_DEFAULT_<ALIAS>_MODEL`
says; unset, it resolves to the Anthropic model ID, which the provider will
not serve — the classic failure is every `Agent` alias launch dying on its
first request with no hint why. This module is the one shared check that turns
that into a loud, actionable configuration error before any phase launches a
reviewer or implementer (`references/models.md`).

Two surfaces:

  * `read_claude_code_profile(env)` — the env-derived capability profile of
    the Claude Code runtime with an Anthropic-compatible gateway. It reads
    `ANTHROPIC_BASE_URL` and the `ANTHROPIC_DEFAULT_<ALIAS>_MODEL` family and
    reports what it can prove. A capability it cannot determine from the
    environment is recorded as "unknown" and is NEVER guessed: the SDD core
    consumes this profile without knowing or assuming the concrete source.
  * `alias_warnings(aliases, env)` + the `check --aliases ...` CLI — the
    preflight a phase runs before its first `Agent` launch. One actionable
    warning per alias lacking its mapping when `ANTHROPIC_BASE_URL` is set;
    nothing when it is unset (native Anthropic needs no mapping); a full model
    name passes through untouched.

This module implements the Claude Code env-derived source only (D2): there is
no runtime auto-detection. Another runtime's change implements its own source
behind the same conceptual interface — the SDD core never knows which source a
profile came from.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, Mapping

# The only aliases Claude Code resolves through ANTHROPIC_DEFAULT_<ALIAS>_MODEL.
ALIAS_ENV = {
    "haiku": "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "sonnet": "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "opus": "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "fable": "ANTHROPIC_DEFAULT_FABLE_MODEL",
}

# Capabilities the Claude Code environment exposes no variable for; they stay
# "unknown" until a determinable signal exists. Honesty over guesses (R1).
UNDETERMINED = "unknown"


def read_claude_code_profile(env: Mapping[str, str] | None = None) -> dict:
    """The Claude Code env-derived capability profile.

    Returns {"base_url", "alias_map", "structured_output", "effort",
    "budget_semantics", "fallback"}: `base_url` is None when
    `ANTHROPIC_BASE_URL` is unset; `alias_map` holds only the aliases whose
    `ANTHROPIC_DEFAULT_<ALIAS>_MODEL` is set; every capability that cannot be
    determined from the environment is the string "unknown", never a guessed
    provider value.
    """
    env = os.environ if env is None else env
    return {
        "base_url": env.get("ANTHROPIC_BASE_URL"),
        "alias_map": {
            alias: env[variable]
            for alias, variable in ALIAS_ENV.items()
            if env.get(variable)
        },
        "structured_output": UNDETERMINED,
        "effort": UNDETERMINED,
        "budget_semantics": UNDETERMINED,
        "fallback": UNDETERMINED,
    }


def alias_warnings(aliases: Iterable[str], env: Mapping[str, str] | None = None) -> list[str]:
    """One actionable warning per alias that would resolve to an Anthropic
    model ID behind a custom `ANTHROPIC_BASE_URL` (R2).

    Returns [] when `ANTHROPIC_BASE_URL` is unset (native Anthropic serves the
    IDs) and [] for any name that is not one of the four aliases — a full
    model name needs no mapping and passes through untouched.

    Each name is stripped of surrounding whitespace before the lookup, so a
    padded alias (' opus') is checked as ' opus'.stripped() == 'opus', not
    silently passed through as a full model name. An empty or all-whitespace
    name is skipped here; it is the caller's job to reject a list that expands
    to nothing (the CLI does — see `main`) so the mandatory preflight cannot
    become a no-op. `alias_warnings([])` itself legitimately returns []:
    `sdd_auto_outcome` calls it with a single model after its own checks, so
    emptiness is meaningful there, not a malformed invocation.
    """
    env = os.environ if env is None else env
    if not env.get("ANTHROPIC_BASE_URL"):
        return []
    warnings = []
    for alias in aliases:
        variable = ALIAS_ENV.get(alias.strip().lower())
        if variable and not env.get(variable):
            warnings.append(
                f"ANTHROPIC_BASE_URL is set but {variable} is not: the alias {alias!r} "
                "will resolve to the Anthropic model ID, which this provider may not serve."
            )
    return warnings


def main(argv: list[str] | None = None) -> int:
    """`check --aliases sonnet,opus` — the phase preflight.

    `--aliases` takes a comma-separated list; the flag may also be repeated
    (`--aliases sonnet --aliases opus`), each occurrence contributing aliases.
    Warnings go to stderr; exit 1 when any mapping is missing, 0 otherwise.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser(
        "check",
        help="fail closed on unmapped aliases behind ANTHROPIC_BASE_URL",
    )
    check.add_argument(
        "--aliases",
        action="append",
        required=True,
        help="comma-separated aliases (haiku,sonnet,opus,fable); repeatable",
    )

    args = parser.parse_args(argv)

    if args.command == "check":
        aliases = [name for group in args.aliases for name in group.split(",") if name.strip()]
        if not aliases:
            print(
                "check: --aliases expanded to an empty list; pass at least one "
                "alias (haiku, sonnet, opus, fable) — e.g. --aliases sonnet,opus",
                file=sys.stderr,
            )
            return 2
        warnings = alias_warnings(aliases)
        for warning in warnings:
            print(warning, file=sys.stderr)
        return 1 if warnings else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
