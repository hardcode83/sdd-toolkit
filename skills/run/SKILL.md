---
name: run
model: sonnet
description: Implement an SDD change by executing its tasks.md in order, checking tasks off as they are verified. Use when the user runs /sdd:run after tasks are approved.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Run

Execute the implementation. Arguments: the feature name (if omitted and exactly one non-archived change exists in `sdd/changes/`, use it), plus an optional mode:

- default — run all remaining tasks sequentially.
- `next` — run only the next unchecked task, then stop for review.

## Steps

1. **Load context.** Read `sdd/project.md` and the change's `proposal.md`, `design.md` (if any), and `tasks.md`. If `tasks.md` doesn't exist, stop and point to `/sdd:tasks`. Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> run` (silent no-op if tracking is disabled).
   - **Steering**: if `sdd/steering/` exists, read each doc's frontmatter and fully load those whose `phases` (if present) include `run` and whose `applies_to` (if present) matches the files this change touches. Re-check when a task takes you into files of a scope not yet loaded (e.g. the first task touching `infra/`).
2. **Execute tasks strictly in order.** For each unchecked task:
   - Implement it following the design decisions and the conventions in `project.md`.
   - Verify it (run the relevant tests/lint from `project.md` — don't wait for the final section to find breakage).
   - Only then mark it `[x]` in `tasks.md`. Never check off unverified work.
3. **On deviation:** if implementation reveals the design or a requirement is wrong, STOP. Explain the conflict, agree the fix with the user, update `proposal.md`/`design.md`/`tasks.md` to match reality, then continue. Never silently diverge from the spec — the documents must stay true.
4. **On blockers** (failing environment, missing credentials, ambiguous requirement): stop and ask rather than guessing around it.
5. **Finish.** When all tasks are checked, run the full Verification section, report results honestly (including anything skipped or failing), then run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> run` (silent no-op if tracking is disabled — in `next` mode run it at each stop too; the row is recomputed, not duplicated). Suggest `/sdd:archive` — optionally preceded by `/sdd:review <feature>`.

Scope discipline: implement only what tasks describe. If you spot valuable extra work, note it as a candidate for a future change instead of doing it.
