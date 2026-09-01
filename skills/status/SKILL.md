---
name: status
model: haiku
effort: low
context: fork
background: false
description: Show the state of SDD changes - active changes, phase, task progress, and the roadmap as derived views (what is workable now in parallel, dependency waves, critical path per stage, dependency graph). With a feature name, drills into that change's tasks.md - full plan, or filtered by section/pending/done/requirement, for surgical navigation of large task lists. Use when the user runs /sdd:status or asks where a change/the roadmap/a specific task stands, or what can be worked on next.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Status

Report the state of the SDD workflow. Read-only — change nothing. Arguments: none (overview, below), or `<feature> [filter]` (task plan view, see "Task plan view").

## Overview (no arguments) — Steps

1. List non-archived directories in `sdd/changes/`. For each, determine:
   - **Lifecycle**: read `STATE.md` when present and show `ACTIVE`,
     `LOCAL_VERIFIED`, `READY_FOR_PR`, `PR_OPEN`, `MERGED`, or `CANCELLED`.
     No `STATE.md` means a legacy active change; derive only its document
     phase and never infer PR/merge state.
   - **Phase**: which of `proposal.md` / `design.md` / `tasks.md` exist.
   - **Progress**: if `tasks.md` exists, count `- [x]` vs `- [ ]` (e.g. `grep -c '^\s*- \[x\]'`).
   - **Pending queue**: if `BLOCKED.md` exists, this change has unresolved entries — show these FIRST, each with its type (`decision`: needs the user / `deferred`: resumable — show its resume command) and one-line reason. This is the user's inbox: decisions to make and deferred work to pick up.
2. **Other worktrees of this repo** (shared rule 10 — a change may not be in *this* directory at all):

   ```bash
   git worktree list
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . list
   ```

   Step 1 only sees the `sdd/changes/` of the current working directory, so a feature isolated in a sibling worktree would be invisible. For each worktree other than this one, read its `sdd/changes/*/STATE.md` too and include those changes in the table, labelled with the worktree they live in. Also report **live sessions** (`list` prints them, pruned by process liveness): that is what tells the user another session is holding a feature right now. Bindings whose worktree is gone are reported by `/sdd:doctor`, not here.
3. **In progress by others** (only if the repo has a git remote): `git ls-remote --heads origin "sdd/*"` — list remote SDD branches that don't correspond to a local active change, as "en curso por otros" (branch name; add author/date via `git log -1` on the fetched ref if cheap). This completes the picture: claims live as remote branches before they're merged.
4. Count capability specs in `sdd/specs/` and recent entries in `sdd/changes/archive/`.
5. If `sdd/roadmap.md` exists, get the derived roadmap views — do not hand-render them, and never infer order from line position:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_roadmap.py" --root . report
   ```

   Relay its sections as they come: **frontera** (what can be worked right now, in parallel — each entry annotated with how many others it unblocks, so the user can choose), **olas** (topological levels), **camino crítico** per stage (the chain that parallel work cannot shorten), **aplazadas**, and the **grafo** — which is **text, laid out by wave**, each entry naming what it waits on (`◂ necesita`) and what it unblocks (`▸ desbloquea`). Relay that text **verbatim**. Do not redraw it, do not summarise it, and do not convert it into a diagram format: terminal text is the only rendering on purpose, because a format the terminal cannot draw forces the user out of the tool to see their own graph. The status symbols (`✔` archived, `PR` `PR_OPEN`, `✓` `READY_FOR_PR`, `▶` active, `⛔` blocked, `·` pending) are derived from each change's `STATE.md` and `BLOCKED.md`, never from the roadmap text — a checked entry whose change is still active is inconsistent, not done, and `/sdd:doctor` is what reports it.

   When the roadmap declares no relations (a flat legacy roadmap), the report says so explicitly instead of drawing a one-level graph that would fake information. Pass `--stage <n>` to narrow to one stage. If the report's **Problemas** section is non-empty, show it and point to `/sdd:doctor`.

   The report also carries **Posibles dependencias sin declarar**: relations the prose states that the metadata does not. They are found deterministically on every run, so they track the prose instead of going stale — but they order **nothing**. Relay them as the questions they are, with their quotes, and say plainly that declaring one is what makes it count. Never present a candidate as a dependency, and never reorder anything by it: `frontier`, `waves` and `/sdd:auto` read declared edges only, precisely so a misread paragraph cannot change what gets built next. `sdd_roadmap.py suggest --only-open` is the narrower view when the list is long — a closed target cannot change the order.
6. Present a compact table: change · lifecycle · document phase · tasks done/total · worktree (only when it isn't this directory) · PR · suggested next action. Use `/sdd:design`, `/sdd:tasks`, or `/sdd:run` for active work; open/record a PR for `READY_FOR_PR`; wait for merge then `/sdd:archive` for `PR_OPEN`; `/sdd:archive` for `MERGED`. Never suggest archive merely because all local tasks are checked.

If `sdd/` doesn't exist, say so and point to `/sdd:init`. If there are no active changes, say so and point to `/sdd:new` (suggesting the first entry of the frontier if there is one — not the first line of the roadmap).

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
