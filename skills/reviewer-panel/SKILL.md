---
name: reviewer-panel
description: Shared logical reviewer planning, Claude compatibility dispatch, native Codex panel dispatch, and fail-closed result validation.
---

# SDD reviewer panel

The panel has one logical source of truth: `reviewer_plan.py` and the three
definitions in `reviewers/`. Build one `ReviewerPlan` before choosing a
runtime. The mandatory core is always `sdd-architect`, `sdd-security`, and
`sdd-qa`; project `.claude/agents/sdd-review-*.md` files are additive.

## Dispatch contract

`build_reviewer_plan(root, phase, scope)` is the only selector. `MATCH` and
`UNKNOWN` project reviewers run; only definitive `NO MATCH` may be recorded as
`skipped`. Core reviewers never go through applicability filtering. Every
request carries the feature, exact `scope_id`, scope, lens, criteria,
requirements/design/tasks referents, and the read-only boundary.

`dispatch_claude_panel()` is the compatibility boundary. Launch every planned
item in one parallel assistant message using the existing Claude agent names,
wait for every response, and normalize exactly one result per planned item.
MiniMax-through-Claude uses this same boundary. An unavailable or malformed
response is synthesized as an explicit unavailable result and cannot pass.

`dispatch_codex_panel()` is the native boundary. In one parallel batch, spawn
one native Codex subagent per planned item with the current feature worktree,
read-only filesystem, no lifecycle commands, no repository mutation, and no
network/external side effects. Bind each returned native handle to the planned
reviewer identity; self-reported identity never overrides that binding. Wait
on every handle, collect exactly one structured response, and check the
worktree before and after collection. If spawn, parallelism, wait, collection,
sandbox, or worktree binding cannot be enforced, return unavailable results.
Do not use `.codex/agents`, `~/.codex/agents`, copied prompts, symlinks, or
project Codex configuration.

The executable lifecycle boundary is `execute_lifecycle_panel()` (with the
thin `run_panel()`, `review_panel()`, and `auto_panel()` entry points). Each
entry point builds the plan, invokes the selected adapter, re-evaluates the
returned results through the shared gate, and returns a non-passing result on
any malformed adapter output. Lifecycle skills must call this boundary before
section PASS annotation or certification; this module itself never writes
`STATE.md`.

For shell lifecycle entry points, `scripts/reviewer_panel.py` is the same
closed-world gate: pass the exact phase scope and collected transport JSON;
continue to annotation/certification only on exit 0. A non-zero exit is a
visible fail-closed result.

## Result gate

Use `normalize_reviewer_result()` and `evaluate_panel_gate()` before annotating
`tasks.md` or invoking any lifecycle certification command. A PASS requires a
valid mandatory-core registry, one complete in-scope PASS for every required
plan item, and only definitive NO MATCH skips. Missing, duplicate, unknown,
spoofed, mismatched, timed-out, interrupted, malformed, out-of-scope, or
unavailable results fail closed. This module never writes `STATE.md`.
