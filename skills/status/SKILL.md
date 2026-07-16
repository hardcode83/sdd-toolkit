---
name: status
model: haiku
description: Show the state of SDD changes - active changes, phase, task progress, and the roadmap as a to-do view. Use when the user runs /sdd:status or asks where a change or the roadmap stands.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Status

Report the state of the SDD workflow. Read-only — change nothing.

## Steps

1. List non-archived directories in `sdd/changes/`. For each, determine:
   - **Phase**: which of `proposal.md` / `design.md` / `tasks.md` exist.
   - **Progress**: if `tasks.md` exists, count `- [x]` vs `- [ ]` (e.g. `grep -c '^\s*- \[x\]'`).
2. Count capability specs in `sdd/specs/` and recent entries in `sdd/changes/archive/`.
3. If `sdd/roadmap.md` exists, render it as a to-do view preserving order — one line per entry with its state: `✔` done (checked off), `▶` in progress (annotated with `→ changes/<feature>/` and not yet archived), `·` pending. Keep each line to the feature name + a few words; mark which pending entry is next.
4. Present a compact table: change · phase · tasks done/total · suggested next command (`/sdd:design`, `/sdd:tasks`, `/sdd:run`, or `/sdd:archive`). Below it, the roadmap to-do view with a progress count (e.g. `2/13`).

If `sdd/` doesn't exist, say so and point to `/sdd:init`. If there are no active changes, say so and point to `/sdd:new` (suggesting the next roadmap entry if there is one).
