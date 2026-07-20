---
name: tasks
model: sonnet
description: Break an SDD change into an implementation checklist (sdd/changes/<feature>/tasks.md) of small, verifiable tasks referencing the requirements. Use when the user runs /sdd:tasks after proposal (and design, if any) are approved.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Tasks

Produce the implementation checklist. Argument: the feature name; if omitted and exactly one non-archived change exists in `sdd/changes/`, use it — otherwise ask.

## Steps

1. **Load context.** Read `sdd/project.md`, the change's `proposal.md`, and `design.md` if it exists. If there is no proposal, stop and point to `/sdd:new`. Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> tasks` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled).
   - **Steering**: if `sdd/steering/` exists, read each doc's frontmatter and fully load those whose `phases` (if present) include `tasks` and whose `applies_to` (if present) matches the change's scope.
2. **Write** `sdd/changes/<feature>/tasks.md` using `${CLAUDE_PLUGIN_ROOT}/templates/tasks-template.md`. Rules:
   - Tasks are grouped in numbered sections, ordered so the system stays working after each section when possible.
   - Each task is a checkbox, small enough to complete and verify in one sitting, and states **which files** it touches and **which requirement(s)** it satisfies (`[R1]`).
   - Testing is part of the task that introduces the behavior, not a separate "write tests" section at the end. A final section covers integration/verification using the exact commands from `sdd/project.md`.
   - Only coding/verification activities — no "deploy to prod", "get approval" or meeting-shaped tasks.
   - Every requirement must be covered by at least one task; check this before finishing.
   - **Adopted in-flight work**: if part of the change is already implemented, include those tasks anyway and pre-check them `[x]` — but only after verifying each against the actual code (and its tests), noting `(preexistente)`. Never pre-check on the user's word alone.
3. **Metrics.** Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> tasks` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled).
4. **Gate.** Show the full `tasks.md` you just wrote (every section and task, not just a count — the user is approving the actual checklist, not a summary of it), wait for approval, then suggest `/sdd:run`.
