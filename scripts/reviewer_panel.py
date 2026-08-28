#!/usr/bin/env python3
"""Executable lifecycle gate for the shared reviewer panel.

Runtime skills perform spawning; this command is the deterministic boundary
that plans the expected set and validates collected JSON before lifecycle
annotation or certification commands are allowed to run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "skills" / "reviewer-panel" / "reviewer_plan.py"
import importlib.util
spec = importlib.util.spec_from_file_location("sdd_reviewer_plan_cli", MODULE)
assert spec and spec.loader
reviewer_plan = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reviewer_plan
spec.loader.exec_module(reviewer_plan)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--phase", choices=sorted(reviewer_plan.VALID_PHASES), required=True)
    parser.add_argument("--feature", required=True)
    parser.add_argument("--scope", required=True, help="JSON scope object")
    parser.add_argument("--results", required=True, help="JSON list of normalized transport results")
    parser.add_argument("--codex-handoff", help="JSON top-level Codex harness handoff")
    parser.add_argument("--worktree", type=Path, help="feature worktree for a Codex handoff")
    parser.add_argument("--solo", action="store_true")
    args = parser.parse_args(argv)
    try:
        scope = json.loads(args.scope)
        raw_results = json.loads(args.results)
        if not isinstance(scope, dict) or not isinstance(raw_results, list):
            raise ValueError("scope must be an object and results must be a list")
        plan = reviewer_plan.build_reviewer_plan(args.root, args.phase, scope, solo=args.solo)
        if args.solo:
            panel = reviewer_plan.PanelResult(plan, [], "FAIL", ["solo bypass cannot produce panel PASS"])
        elif args.codex_handoff:
            if not args.worktree:
                raise ValueError("--worktree is required with --codex-handoff")
            handoff = json.loads(args.codex_handoff)
            panel = reviewer_plan.dispatch_codex_panel(plan, handoff, args.feature, args.worktree)
        else:
            required_items = [p for p in plan if p.required]
            if len(raw_results) != len(required_items):
                raise ValueError("result collection is incomplete or contains extra results")
            results = []
            for item, payload in zip(required_items, raw_results):
                results.append(reviewer_plan.normalize_reviewer_result(payload, item))
            panel = reviewer_plan.evaluate_panel_gate(plan, results)
        print(json.dumps(panel.to_dict(), sort_keys=True))
        return 0 if panel.passed else 1
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"gate": "FAIL", "errors": [str(exc)]}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
