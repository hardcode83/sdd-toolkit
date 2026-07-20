---
name: status
model: haiku
description: Show the state of SDD changes - active changes, phase, task progress, and the roadmap as a to-do view. With a feature name, drills into that change's tasks.md - full plan, or filtered by section/pending/done/requirement, for surgical navigation of large task lists. Use when the user runs /sdd:status or asks where a change/the roadmap/a specific task stands.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Status

Report the state of the SDD workflow. Read-only — change nothing. Arguments: none (overview, below), or `<feature> [filter]` (task plan view, see "Task plan view").

## Overview (no arguments) — Steps

1. List non-archived directories in `sdd/changes/`. For each, determine:
   - **Phase**: which of `proposal.md` / `design.md` / `tasks.md` exist.
   - **Progress**: if `tasks.md` exists, count `- [x]` vs `- [ ]` (e.g. `grep -c '^\s*- \[x\]'`).
   - **Pending queue**: if `BLOCKED.md` exists, this change has unresolved entries — show these FIRST, each with its type (`decision`: needs the user / `deferred`: resumable — show its resume command) and one-line reason. This is the user's inbox: decisions to make and deferred work to pick up.
2. **In progress by others** (only if the repo has a git remote): `git ls-remote --heads origin "sdd/*"` — list remote SDD branches that don't correspond to a local active change, as "en curso por otros" (branch name; add author/date via `git log -1` on the fetched ref if cheap). This completes the picture: claims live as remote branches before they're merged.
3. Count capability specs in `sdd/specs/` and recent entries in `sdd/changes/archive/`.
4. If `sdd/roadmap.md` exists, render it as a to-do view preserving order — one line per entry with its state: `✔` done (checked off), `▶` in progress (annotated with `→ changes/<feature>/` and not yet archived, or claimed by a remote `sdd/*` branch), `·` pending. Keep each line to the feature name + a few words; mark which pending entry is next.
5. Present a compact table: change · phase · tasks done/total · suggested next command (`/sdd:design`, `/sdd:tasks`, `/sdd:run`, or `/sdd:archive`). Below it, the roadmap to-do view with a progress count (e.g. `2/13`).

If `sdd/` doesn't exist, say so and point to `/sdd:init`. If there are no active changes, say so and point to `/sdd:new` (suggesting the next roadmap entry if there is one).

## Task plan view (`<feature> [filter]`)

For navigating a large `tasks.md` surgically — finding the exact task number to target with `/sdd:run <feature> <task>`, or checking what's left, without regenerating or editing anything.

1. Locate the change (active in `sdd/changes/<feature>/`, or archived under `sdd/changes/archive/*-<feature>/`) and read its `tasks.md`. No `tasks.md` → say so and point to `/sdd:tasks <feature>`.
2. Apply the filter, if given:
   - No filter → the full plan: every section heading (with its `<!-- panel: PASS ... -->` annotation if present) and every task/subtask with its `[x]`/`[ ]` state and `[R#]` tags.
   - A section number (e.g. `4`) → only that section's tasks.
   - A task/subtask number (e.g. `2.3`) → just that task, its subtasks if any, and one line of surrounding context (its section heading).
   - `pending` / `done` → only unchecked / only checked tasks, across all sections, each still labeled with its number so it can be fed straight into `/sdd:run <feature> <n.n>`.
   - `R<n>` (e.g. `R5`) → only tasks tagged `[R5]` — useful to see everything implementing one requirement.
3. Render as a checklist (not prose), preserving numbering — the point is a scannable, copy-pasteable view, not a summary.

This is purely mechanical parsing of an existing file — never write to `tasks.md`, never mark anything, never regenerate it (that's `/sdd:tasks`'s job, which now guards existing content per shared rule 6).
