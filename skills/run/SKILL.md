---
name: run
model: sonnet
description: Implement an SDD change by executing its tasks.md in order, checking tasks off as they are verified. Use when the user runs /sdd:run after tasks are approved.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Run

Execute the implementation. Arguments: the feature name (if omitted and exactly one non-archived change exists in `sdd/changes/`, use it), plus an optional mode:

- default — run all remaining tasks sequentially, with the review panel after each section.
- `next` — run only the next unchecked task, then stop for review.
- `solo` — skip the review panel entirely (cheap mode for scaffolding-heavy changes).
- `tournament <task>` — parallel-generation for ONE hard task, where `<task>` is the task's number as written in the change's `tasks.md` (e.g. `2.1`) or enough of its description to identify it unambiguously. It must be a single unchecked task; the rest of the change runs normally. See step 6. Never the default.

## Steps

1. **Load context.** Read `sdd/project.md` and the change's `proposal.md`, `design.md` (if any), and `tasks.md`. If `tasks.md` doesn't exist, stop and point to `/sdd:tasks`. Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> run` (silent no-op if tracking is disabled).
   - **Steering**: if `sdd/steering/` exists, read each doc's frontmatter and fully load those whose `phases` (if present) include `run` and whose `applies_to` (if present) matches the files this change touches. Re-check when a task takes you into files of a scope not yet loaded (e.g. the first task touching `infra/`).
2. **Execute tasks strictly in order.** For each unchecked task:
   - Implement it following the design decisions and the conventions in `project.md`.
   - Verify it (run the relevant tests/lint from `project.md` — don't wait for the final section to find breakage).
   - Only then mark it `[x]` in `tasks.md`. Never check off unverified work.
3. **Review panel — after each completed section.** When the last task of a numbered section is checked and the section touched production code (skip it for pure scaffolding/docs/config sections, and in `solo` mode), launch the three reviewer agents **in parallel** (one message, three Agent calls — types `sdd-architect`, `sdd-security`, `sdd-qa`). Give each: the feature name, the requirement IDs (R#) the section covers, and the exact scope (files changed / git diff range since the section started).
   - **Referent filter**: discard any finding that doesn't cite its referent (R#, design decision D#, or a quoted steering rule) — the agents are instructed this way, enforce it when synthesizing.
   - Fix the accepted findings, then re-run **only the reviewer(s) whose findings you fixed**, scoped to the fix. Maximum 2 fix rounds per section; if findings persist after that, stop and present them to the user.
   - A `DESIGN-CONFLICT` from the architect is not a code fix — it goes through the deviation rule (step 4).
   - If a reviewer agent type isn't available, say so and continue with the rest — a degraded panel beats a blocked run.
4. **On deviation:** if implementation reveals the design or a requirement is wrong, STOP. Explain the conflict, agree the fix with the user, update `proposal.md`/`design.md`/`tasks.md` to match reality, then continue. Never silently diverge from the spec — the documents must stay true.
5. **On blockers** (failing environment, missing credentials, ambiguous requirement): stop and ask rather than guessing around it.
6. **Tournament mode** (only when the user explicitly asked for `tournament <task>`): for that ONE task, launch 3 general-purpose agents in parallel, each with `isolation: worktree`, each implementing the same task from the same design — prompt them with different angles (e.g. simplest-correct, performance-first, defensive). When all finish, have the review panel judge the three diffs against the same referents, pick the winner, apply it to the working tree, and graft any clearly better ideas from the losers. Cost is ~3×+ — reserve it for tasks where solution variance is real (algorithms, state machines, tricky concurrency), never for CRUD.
7. **Finish.** When all tasks are checked, run the full Verification section, report results honestly (including anything skipped or failing), then run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> run` (silent no-op if tracking is disabled — in `next` mode run it at each stop too; the row is recomputed, not duplicated). Suggest `/sdd:archive` — optionally preceded by `/sdd:review <feature>`.

Scope discipline: implement only what tasks describe. If you spot valuable extra work, note it as a candidate for a future change instead of doing it.
