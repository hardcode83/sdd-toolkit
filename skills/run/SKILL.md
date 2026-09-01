---
name: run
model: sonnet
description: Implement an SDD change by executing its tasks.md in order, one fresh implementer subagent per section, with the review panel after each section. Use when the user runs /sdd:run after tasks are approved.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Run

You are the **orchestrator** of the implementation, not the implementer. Your
context must stay flat for the whole run: you read the plan, delegate each
section to a fresh subagent, launch the panel on what it produced, and record
verdicts. Diffs, test output and reviewer prose never enter this conversation
in full — that is what made `run` 56% of a real project's spend, at 444k of
context per request (`${CLAUDE_PLUGIN_ROOT}/references/context-budget.md`).

The review panel is the shared logical plan and closed-world gate of
`${CLAUDE_PLUGIN_ROOT}/skills/reviewer-panel/SKILL.md`: build one plan per
section (`build_reviewer_plan`), dispatch it through the runtime's boundary,
and write `panel: PASS` only after `scripts/reviewer_panel.py --phase run`
exits 0. A missing, unavailable or malformed reviewer result fails closed and
is never replaced inline.

Arguments: the feature name (if omitted and exactly one non-archived change
exists in `sdd/changes/`, use it), plus an optional scope/mode (addresses
refer to the numbering in the change's `tasks.md`):

- default — run ALL remaining tasks, section by section, with the review panel after each section.
- `next [N]` — run only the next N unchecked tasks (default 1), then stop for review.
- `<section>` (e.g. `2`) — run only that section's pending tasks; panel at its close.
- `<task>` (e.g. `2.3`) — run only that task (and its subtasks). The panel fires when a section *completes*, so a lone task triggers it only if it was the section's last unchecked one.
- `solo` — skip the review panel entirely (cheap mode for scaffolding-heavy changes). Combinable with a scope: `2 solo`. Never records a panel PASS.
- `tournament <task>` — parallel generation for ONE hard task. Follow `${CLAUDE_PLUGIN_ROOT}/skills/tournament/SKILL.md` for that task (it is also `/sdd:tournament <feature> <task>`); the rest of the change runs normally. Never the default.

**Out-of-order guard**: `tasks.md` is ordered so the system stays working after each section. If the requested scope would leave *earlier* unchecked tasks behind (e.g. `3.2` while section 1 has pending tasks), say so and get the user's confirmation before proceeding — the order exists for a reason, but the user may know better (e.g. a task parked on purpose).

## Steps

1. **Load context.** Read `sdd/project.md` and the change's `proposal.md`, `design.md` (if any), and `tasks.md` — including its `## Implementation Notes` section if present. If `tasks.md` doesn't exist, stop and point to `/sdd:tasks`. Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> run` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled).
   - **Worktree, then the branch guard** (shared rule 10 — this is the phase that writes code, so it matters most here):
     1. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . resolve <feature>` — if it prints a path that is not the current directory, enter it with `EnterWorktree` (`path`). Nothing printed → run `… check --feature <feature>` and obey its last line, per `${CLAUDE_PLUGIN_ROOT}/references/isolation.md`. One exception, and it is important: if that line says `ISOLATE` only because the project declares `isolation: always`, the feature should already have had a worktree since `/sdd:new` — it started before the policy, or the user declined. **Say that, and do not move work retroactively**: creating a worktree now while this clone holds the change's uncommitted files is the branch-drift failure rule 10 exists to prevent. Isolate only if the tree is clean, and otherwise finish the change where it lives.
     2. **Before the first edit**, verify `git branch --show-current` is `sdd/<feature>` (or the branch `STATE.md` records). If it is not, **STOP** and report it — do not "fix" it with a checkout, which can drag another session's uncommitted files onto this branch. This guard exists because `mark-ready` records `head_branch` and `implementation_sha` as the merge gate's evidence: writing code from the wrong branch does not just conflict, it makes that evidence false.
   - **Steering**: if `sdd/steering/` exists, read each doc's frontmatter and note which docs apply to `run` and to the files this change touches (`${CLAUDE_PLUGIN_ROOT}/references/steering.md`). You will quote the rules that bind each section into that section's implementer and reviewer prompts; you do not need every doc in full yourself.
2. **Delegate each section to a fresh implementer.** For every section in scope with unchecked tasks, in order, launch **one** `Agent` (general-purpose) and wait for it. The implementer starts with an empty context, so the prompt must be complete:
   - the feature, the worktree path (absolute — `cd` does not persist in a subagent, so every command it runs is `cd <path> && …`), and the branch it must be on (rule 10's guard, verified before its first edit);
   - the section's tasks **verbatim** from `tasks.md`, with the requirement IDs they cite **and the EARS text of those R#**, the design decisions (D#) that apply **quoted**, the steering rules that bind these files **quoted**, the exact test/lint commands from `project.md`, and the current `## Implementation Notes`;
   - the contract: implement the tasks strictly in order; verify each one (run the relevant tests — do not wait for the last section to find breakage) and only then mark it `[x]` in `tasks.md`; never check off unverified work; implement only what the tasks describe; append to `## Implementation Notes` in `tasks.md` (create the section if missing) the decisions, names and gotchas the next section needs — one bullet each, no prose; on a design or requirement conflict, or on a blocker (failing environment, missing credentials, ambiguous requirement), **stop and report it** instead of guessing around it;
   - the return format: a report of at most ~30 lines — tasks completed (numbers), files created/modified (paths), commands run with pass/fail counts, notes appended, and any `CONFLICT`/`BLOCKER` with its cause. **No diffs, no logs.**

   **Model.** Sonnet by default (`model: sonnet` on the `Agent` call). A section whose heading carries `<!-- hard -->` — set by `/sdd:tasks` or by the user for algorithms, state machines, tricky concurrency — gets `model: opus`. Never escalate on your own initiative; a section that turns out harder than planned is a note for the user at the gate, not a silent model change.

   **Trust the disk, not the report** (shared rule 11): after the implementer returns, read the section in `tasks.md` to confirm which boxes are checked, and `git status --porcelain` / `git diff --stat` for the file list. If the implementer stopped on a `CONFLICT`, go to step 4; on a `BLOCKER`, step 5. If it checked tasks it reports as unverified, uncheck them and say so.

   **Runtime without subagents** (Codex today, or a session where `Agent` is unavailable): implement the section yourself, with exactly the contract above as your checklist — same order, same verification before `[x]`, same notes. The delegation is a cost optimisation; the contract is the phase.
3. **Review panel — after each completed section.** When the last task of a numbered section is checked and the section touched production code (skip it for pure scaffolding/docs/config sections, and in `solo` mode), launch the review panel **in parallel** (one message, one `Agent` call per reviewer):
   - **Core reviewers (always)**: types `sdd-architect`, `sdd-security`, `sdd-qa`.
   - **Project reviewers (additive)**: every agent the project defines at `.claude/agents/sdd-review-*.md` (agent type = the file's `name`; discover with a glob before launching), filtered by the shared plan: a reviewer whose `phases`/`applies_to` definitively exclude this section's files is recorded as skipped; one without that metadata runs on every section (`/sdd:doctor` reports those as `SDD028`).

   **One message, every reviewer in it.** All the `Agent` calls go in a *single*
   assistant message — one tool call each, sent together. One call per message
   costs 2N round-trips of this context instead of 2, and lets each reviewer's
   prompt be written after reading the previous reviewer's findings, which is
   exactly the independence the panel exists to buy. In the first measured corpus
   **481 of 481** panel launches were sequential — treat a lone `Agent` call in a
   message as the bug it is.

   **Give each reviewer its referents inline, don't send it hunting.** You hold
   the plan; the reviewers do not, and left to rediscover it they averaged 60
   tool-call turns each. Every panel prompt carries: the feature name, the exact
   `scope_id` and file list (the implementer's), the requirement IDs (R#) in scope
   **with their EARS text**, the design decisions (D#) that apply **quoted**, the
   steering rules that bind this scope **quoted**, and the exact diff range. The
   agent files tell them to read these; a prompt that already carries them turns
   reading into verifying.

   **Results are JSON, not reports.** Each reviewer's final message is the result
   envelope of `reviewer_plan.py` (`reviewer_id`, `scope_id`, `lens`, `verdict`,
   `findings`, `evidence`, `status`) and nothing else — the agent files carry the
   exact shape. Feed the envelopes to `scripts/reviewer_panel.py --phase run`
   with the section's scope; its exit code is the gate. Read the findings from
   the JSON; never ask a reviewer to explain itself in prose.
   - **Referent filter**: a finding without its referent (R#, design decision D#, or a quoted steering rule) is discarded — the agents are instructed this way, enforce it when synthesizing.
   - **Fix rounds are delegated too.** Give the accepted findings (file:line, referent, what, fix direction) to a fresh implementer with the same contract as step 2, scoped to those findings; then re-run **only the reviewer(s) whose findings were fixed**, scoped to the fix. Maximum 2 fix rounds per section; if findings persist after that, stop and present them to the user.
   - A `DESIGN-CONFLICT` finding from the architect is not a code fix — it goes through the deviation rule (step 4).
   - If a reviewer cannot be resolved, spawned, waited on, or collected, record an explicit unavailable result. The shared reviewer-panel gate fails closed; do not substitute an inline reviewer for a missing mandatory or applicable reviewer.
   - **Persist the verdict**: when the section ends in PASS, annotate its heading in `tasks.md` with an HTML comment — `## 2. <título> <!-- panel: PASS 2026-07-17 -->` (invisible in rendered markdown; keep any `<!-- hard -->` marker next to it). This is what lets `/sdd:review` be incremental instead of re-auditing everything.
4. **On deviation:** if implementation reveals the design or a requirement is wrong, STOP. Explain the conflict, agree the fix with the user, update `proposal.md`/`design.md`/`tasks.md` to match reality, then continue. Never silently diverge from the spec — the documents must stay true.
5. **On blockers** (failing environment, missing credentials, ambiguous requirement): stop and ask rather than guessing around it. Whatever remains unresolved when the turn ends — including a panel that couldn't run or complete (usage limits, unavailable agents) — goes to `BLOCKED.md` per shared rule 5, with the exact resume command (an interrupted section panel is best resumed as `/sdd:review <feature>`, which covers everything at feature scale).
6. **Finish.** When all tasks are checked, run the full Verification section yourself (its commands come from `project.md`; report results honestly, including anything skipped or failing), then run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> run` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled). Suggest `/sdd:review <feature>` to establish local approval and `READY_FOR_PR`; never suggest archive before PR merge. Review runs forked (shared rule 11), so it will not inherit this context — but the conversation that calls it keeps paying for whatever accumulated here, on every later turn. **Recommend `/clear` first** when the user is going to keep working in this session.

Scope discipline: implement only what tasks describe. If an implementer or you spot valuable extra work, note it as a candidate for a future change instead of doing it.
