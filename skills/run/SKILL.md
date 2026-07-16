---
name: run
model: sonnet
description: Implement an SDD change by executing its tasks.md in order, checking tasks off as they are verified. Use when the user runs /sdd:run after tasks are approved.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Run

Execute the implementation. Arguments: the feature name (if omitted and exactly one non-archived change exists in `sdd/changes/`, use it), plus an optional scope/mode (addresses refer to the numbering in the change's `tasks.md`):

- default — run ALL remaining tasks sequentially, with the review panel after each section.
- `next [N]` — run only the next N unchecked tasks (default 1), then stop for review.
- `<section>` (e.g. `2`) — run only that section's pending tasks; panel at its close.
- `<task>` (e.g. `2.3`) — run only that task (and its subtasks, if it has them). The panel fires when a section *completes*, so a lone task triggers it only if it was the section's last unchecked one.
- `solo` — skip the review panel entirely (cheap mode for scaffolding-heavy changes). Combinable with a scope: `2 solo`.
- `tournament <task>` — parallel-generation for ONE hard task (same addressing, e.g. `2.1`, or enough description to identify it unambiguously). It must be a single unchecked task; the rest of the change runs normally. See step 6. Never the default.

**Out-of-order guard**: `tasks.md` is ordered so the system stays working after each section. If the requested scope would leave *earlier* unchecked tasks behind (e.g. `3.2` while section 1 has pending tasks), say so and get the user's confirmation before proceeding — the order exists for a reason, but the user may know better (e.g. a task parked on purpose).

## Steps

1. **Load context.** Read `sdd/project.md` and the change's `proposal.md`, `design.md` (if any), and `tasks.md`. If `tasks.md` doesn't exist, stop and point to `/sdd:tasks`. Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> run` (silent no-op if tracking is disabled).
   - **Steering**: if `sdd/steering/` exists, read each doc's frontmatter and fully load those whose `phases` (if present) include `run` and whose `applies_to` (if present) matches the files this change touches. Re-check when a task takes you into files of a scope not yet loaded (e.g. the first task touching `infra/`).
2. **Execute tasks strictly in order.** For each unchecked task:
   - Implement it following the design decisions and the conventions in `project.md`.
   - Verify it (run the relevant tests/lint from `project.md` — don't wait for the final section to find breakage).
   - Only then mark it `[x]` in `tasks.md`. Never check off unverified work.
3. **Review panel — after each completed section.** When the last task of a numbered section is checked and the section touched production code (skip it for pure scaffolding/docs/config sections, and in `solo` mode), launch the review panel **in parallel** (one message, one Agent call per reviewer):
   - **Core reviewers (always)**: types `sdd-architect`, `sdd-security`, `sdd-qa`.
   - **Project reviewers (additive)**: every agent the project defines at `.claude/agents/sdd-review-*.md` (agent type = the file's `name`; discover with a glob before launching). They extend the panel with project-specific lenses (performance, i18n, compliance…) and follow the same contract.

   Give each reviewer: the feature name, the requirement IDs (R#) the section covers, and the exact scope (files changed / git diff range since the section started).
   - **Referent filter**: discard any finding that doesn't cite its referent (R#, design decision D#, or a quoted steering rule) — the agents are instructed this way, enforce it when synthesizing.
   - Fix the accepted findings, then re-run **only the reviewer(s) whose findings you fixed**, scoped to the fix. Maximum 2 fix rounds per section; if findings persist after that, stop and present them to the user.
   - A `DESIGN-CONFLICT` from the architect is not a code fix — it goes through the deviation rule (step 4).
   - If a reviewer agent type isn't available, say so and continue with the rest — a degraded panel beats a blocked run.
4. **On deviation:** if implementation reveals the design or a requirement is wrong, STOP. Explain the conflict, agree the fix with the user, update `proposal.md`/`design.md`/`tasks.md` to match reality, then continue. Never silently diverge from the spec — the documents must stay true.
5. **On blockers** (failing environment, missing credentials, ambiguous requirement): stop and ask rather than guessing around it. Whatever remains unresolved when the turn ends — including a panel that couldn't run or complete (usage limits, unavailable agents) — goes to `BLOCKED.md` per shared rule 5, with the exact resume command (an interrupted section panel is best resumed as `/sdd:review <feature>`, which covers everything at feature scale).
6. **Tournament mode** (only when the user explicitly asked for `tournament <task>`): for that ONE task, launch 3 general-purpose agents in parallel, each with `isolation: worktree`, each implementing the same task from the same design — prompt them with different angles (e.g. simplest-correct, performance-first, defensive). When all finish, have the review panel judge the three diffs against the same referents, pick the winner, apply it to the working tree, and graft any clearly better ideas from the losers. Cost is ~3×+ — reserve it for tasks where solution variance is real (algorithms, state machines, tricky concurrency), never for CRUD.
7. **Finish.** When all tasks are checked, run the full Verification section, report results honestly (including anything skipped or failing), then run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> run` (silent no-op if tracking is disabled — in `next` mode run it at each stop too; the row is recomputed, not duplicated). Suggest `/sdd:archive` — optionally preceded by `/sdd:review <feature>`.

Scope discipline: implement only what tasks describe. If you spot valuable extra work, note it as a candidate for a future change instead of doing it.
