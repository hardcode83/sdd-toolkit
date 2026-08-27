---
name: run
model: sonnet
description: Implement an SDD change by executing its tasks.md in order, checking tasks off as they are verified. Use when the user runs /sdd:run after tasks are approved.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Run

For every non-`solo` panel, first build the shared logical plan from
`skills/reviewer-panel/reviewer_plan.py`, then dispatch it through the runtime
boundary described in `skills/reviewer-panel/SKILL.md`. The default Codex path
uses native subagents; Claude and MiniMax use the compatibility boundary. A
section may receive `panel: PASS` only after the closed-world result gate
passes.

Operational gate: `plan = build_reviewer_plan(...)`; `panel =
dispatch_<runtime>_panel(plan, ...)`; continue to section annotation only when
`panel.passed` is true. A missing, unavailable, or invalid panel result stops
the section and cannot be replaced inline.

Execute the implementation. Arguments: the feature name (if omitted and exactly one non-archived change exists in `sdd/changes/`, use it), plus an optional scope/mode (addresses refer to the numbering in the change's `tasks.md`):

- default — run ALL remaining tasks sequentially, with the review panel after each section.
- `next [N]` — run only the next N unchecked tasks (default 1), then stop for review.
- `<section>` (e.g. `2`) — run only that section's pending tasks; panel at its close.
- `<task>` (e.g. `2.3`) — run only that task (and its subtasks, if it has them). The panel fires when a section *completes*, so a lone task triggers it only if it was the section's last unchecked one.
- `solo` — skip the review panel entirely (cheap mode for scaffolding-heavy changes). Combinable with a scope: `2 solo`.
- `tournament <task>` — parallel-generation for ONE hard task (same addressing, e.g. `2.1`, or enough description to identify it unambiguously). It must be a single unchecked task; the rest of the change runs normally. See step 6. Never the default.

**Out-of-order guard**: `tasks.md` is ordered so the system stays working after each section. If the requested scope would leave *earlier* unchecked tasks behind (e.g. `3.2` while section 1 has pending tasks), say so and get the user's confirmation before proceeding — the order exists for a reason, but the user may know better (e.g. a task parked on purpose).

## Steps

1. **Load context.** Read `sdd/project.md` and the change's `proposal.md`, `design.md` (if any), and `tasks.md`. If `tasks.md` doesn't exist, stop and point to `/sdd:tasks`. Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> run` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled).
   - **Worktree, then the branch guard** (shared rule 10 — this is the phase that writes code, so it matters most here):
     1. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . resolve <feature>` — if it prints a path that is not the current directory, enter it with `EnterWorktree` (`path`). Nothing printed → run `… check --feature <feature>` and obey its last line, per `${CLAUDE_PLUGIN_ROOT}/references/isolation.md`. One exception, and it is important: if that line says `ISOLATE` only because the project declares `isolation: always`, the feature should already have had a worktree since `/sdd:new` — it started before the policy, or the user declined. **Say that, and do not move work retroactively**: creating a worktree now while this clone holds the change's uncommitted files is the branch-drift failure rule 10 exists to prevent. Isolate only if the tree is clean, and otherwise finish the change where it lives.
     2. **Before the first edit**, verify `git branch --show-current` is `sdd/<feature>` (or the branch `STATE.md` records). If it is not, **STOP** and report it — do not "fix" it with a checkout, which can drag another session's uncommitted files onto this branch. This guard exists because `mark-ready` records `head_branch` and `implementation_sha` as the merge gate's evidence: writing code from the wrong branch does not just conflict, it makes that evidence false.
   - **Steering**: if `sdd/steering/` exists, read each doc's frontmatter and fully load those whose `phases` (if present) include `run` and whose `applies_to` (if present) matches the files this change touches. Re-check when a task takes you into files of a scope not yet loaded (e.g. the first task touching `infra/`).
2. **Execute tasks strictly in order.** For each unchecked task:
   - Implement it following the design decisions and the conventions in `project.md`.
   - Verify it (run the relevant tests/lint from `project.md` — don't wait for the final section to find breakage).
   - Only then mark it `[x]` in `tasks.md`. Never check off unverified work.
3. **Review panel — after each completed section.** When the last task of a numbered section is checked and the section touched production code (skip it for pure scaffolding/docs/config sections, and in `solo` mode), launch the review panel **in parallel** (one message, one Agent call per reviewer):
   - **Core reviewers (always)**: types `sdd-architect`, `sdd-security`, `sdd-qa`.
   - **Project reviewers (additive)**: every agent the project defines at `.claude/agents/sdd-review-*.md` (agent type = the file's `name`; discover with a glob before launching). They extend the panel with project-specific lenses (performance, i18n, compliance…) and follow the same contract.

   **One message, every reviewer in it.** All the `Agent` calls go in a *single*
   assistant message — one tool call each, sent together. Launching them one per
   message is not a slower version of the same thing, it is a different and worse
   one: it costs 2N round-trips of this context instead of 2 (measured at 411k
   per request during run), and it lets each reviewer's prompt be written after
   reading the previous reviewer's findings, which is exactly the independence the
   panel exists to buy. Measured over 38 sessions of a real project, **481 of 481
   panel launches were sequential** — so treat a lone `Agent` call in a message as
   the bug it is.

   **Give each reviewer its referents inline, don't send it hunting.** You already
   have `proposal.md`, `design.md`, the steering rules and the diff in this
   context; the reviewers do not, and left to rediscover them they averaged **60
   tool-call turns each** in the same corpus. In every panel prompt include: the
   feature name, the requirement IDs (R#) in scope **with their EARS text**, the
   design decisions (D#) that apply **quoted**, the steering rules that bind this
   scope **quoted**, and the exact diff range / file list. The agent files tell
   them to read these; a prompt that already carries them turns reading into
   verifying.
   - **Referent filter**: discard any finding that doesn't cite its referent (R#, design decision D#, or a quoted steering rule) — the agents are instructed this way, enforce it when synthesizing.
   - Fix the accepted findings, then re-run **only the reviewer(s) whose findings you fixed**, scoped to the fix. Maximum 2 fix rounds per section; if findings persist after that, stop and present them to the user.
   - A `DESIGN-CONFLICT` from the architect is not a code fix — it goes through the deviation rule (step 4).
   - If a reviewer cannot be resolved, spawned, waited on, or collected, record an explicit unavailable result. The shared reviewer-panel gate fails closed; do not substitute an inline reviewer for a missing mandatory or applicable reviewer.
   - **Persist the verdict**: when the section ends in PASS, annotate its heading in `tasks.md` with an HTML comment — `## 2. <título> <!-- panel: PASS 2026-07-17 -->` (invisible in rendered markdown). This is what lets `/sdd:review` be incremental instead of re-auditing everything.
4. **On deviation:** if implementation reveals the design or a requirement is wrong, STOP. Explain the conflict, agree the fix with the user, update `proposal.md`/`design.md`/`tasks.md` to match reality, then continue. Never silently diverge from the spec — the documents must stay true.
5. **On blockers** (failing environment, missing credentials, ambiguous requirement): stop and ask rather than guessing around it. Whatever remains unresolved when the turn ends — including a panel that couldn't run or complete (usage limits, unavailable agents) — goes to `BLOCKED.md` per shared rule 5, with the exact resume command (an interrupted section panel is best resumed as `/sdd:review <feature>`, which covers everything at feature scale).
6. **Tournament mode** (only when the user explicitly asked for `tournament <task>`): for that ONE task, launch 3 general-purpose agents in parallel, each with `isolation: worktree`, each implementing the same task from the same design — prompt them with different angles (e.g. simplest-correct, performance-first, defensive). When all finish, have the review panel judge the three diffs against the same referents, pick the winner, apply it to the working tree, and graft any clearly better ideas from the losers. Cost is ~3×+ — reserve it for tasks where solution variance is real (algorithms, state machines, tricky concurrency), never for CRUD.
7. **Finish.** When all tasks are checked, run the full Verification section, report results honestly (including anything skipped or failing), then run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> run` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled). Suggest `/sdd:review <feature>` to establish local approval and `READY_FOR_PR`; never suggest archive before PR merge. **Recommend `/clear` first** (shared rule 11): review is the most expensive phase per request in the whole flow, and run is what filled the context it would inherit — the diffs, test output and panel reports it is about to re-derive from `sdd/` anyway.

Scope discipline: implement only what tasks describe. If you spot valuable extra work, note it as a candidate for a future change instead of doing it.
