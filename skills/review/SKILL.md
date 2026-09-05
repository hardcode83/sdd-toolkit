---
name: review
model: sonnet
context: fork
background: false
description: Detect drift between sdd/specs/ and code, or validate an implemented change locally and mark it READY_FOR_PR. Use when the user runs /sdd:review, asks whether specs are up to date, or wants a spec-vs-implementation check.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Review

The feature-scale panel uses the shared logical plan and result gate in
`skills/reviewer-panel/`; runtime selection must not change reviewer coverage.
For Codex, native child handles are bound to expected reviewer IDs and every
child is waited for and collected under the read-only worktree boundary before
the existing certification sequence can run.

Operational gate: feature review must call `build_reviewer_plan()` once,
dispatch the selected plan through the runtime adapter, and require
`evaluate_panel_gate()`/`PanelResult.passed` immediately before any
`mark-local-verified`, `mark-ready`, or `mark-recertified` command.

The executable feature-review call is `review_panel(...)`; certification is
reachable only after its returned `PanelResult.passed` capability is true.
The shell-facing boundary is `scripts/reviewer_panel.py --phase review`; a
non-zero gate exit prevents all certification commands.

Two modes:

- `<feature>` — **change review**: verify the implementation of `sdd/changes/<feature>/` against its proposal.
- no argument — **drift check**: compare `sdd/specs/` against the codebase.
- `drift` — the drift check named explicitly, for when active changes exist and the caller already chose (see below).

## Choosing the mode when no argument was given

**Look before choosing, and across every worktree.** A feature isolated in its own
worktree committed `sdd/changes/<feature>/` on its branch, so from the main
worktree that change does not exist — and picking the mode by what this directory
happens to contain is how `/sdd:review` silently ran a drift check on somebody who
had just finished implementing. That was survivable while the conversation
remembered which feature was in flight. Once phases start in a fresh context
(shared rule 11) nothing remembers, so ask git:

```bash
git worktree list
```

For this directory and every other worktree, read each `sdd/changes/*/STATE.md`
that is not archived — the same enumeration `/sdd:status` does, and for the same
reason. Then:

- **No active change anywhere** → drift check. If `sdd/specs/` is also missing or
  empty there is nothing to check at all: say so and point to `/sdd:new`.
- **One or more active changes** → both modes are legitimate and you cannot tell
  which was meant, so **hand the choice back** (shared rule 11 — this phase runs
  forked and has no `AskUserQuestion`): end the turn with a `HANDOFF` listing the
  active changes as options, each labelled with its state and the worktree it
  lives in, plus "drift check" as the alternative, and the exact command per
  option (`/sdd:review <feature>` or `/sdd:review drift`). Recommend the change
  whose tasks are all checked — that is the one waiting for exactly this phase.
  Guessing here is not a small error: a drift check reports on specs instead of
  certifying an implementation, and it does it without failing, so the user
  reads a report about the wrong thing.

**Never applies under `/sdd:auto`**, which always passes the feature name.

## Drift check

1. Read `sdd/project.md` and every file in `sdd/specs/`.
2. For each spec requirement, verify the code still behaves that way (read the relevant code; run tests only if cheap).
3. Report a findings list, most severe first:
   - **Broken**: spec says X, code does Y.
   - **Undocumented**: significant behavior with no spec coverage.
   - **Stale**: spec references removed code/features.
4. Offer to update the affected spec files (with user approval, one file at a time).

## Change review

0. **You are running in a fresh context by construction** (shared rule 11): this
   skill declares `context: fork`, so nothing of the conversation that ran
   `/sdd:run` is here — and nothing is missing, because everything this phase
   needs (proposal, design, tasks, the diff, `STATE.md`) is on disk. It used to
   be the most expensive phase per request in the flow (571k of context on
   average in the first measured corpus, 351k in the second) precisely because
   it inherited a long `/sdd:run`. If a runtime runs this skill inline anyway
   (Codex does) and the session already carries the implementation it is about
   to review, say so once and recommend `/clear`; then continue either way —
   this is advice, not
   a gate.

1. **Worktree first** (shared rule 10): `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . resolve <feature>`. If it prints a path that is not the current directory, work there for the rest of the phase: prefix every command with `cd <path> &&` (or pass `--root <path>` to the SDD scripts) and read files by absolute path — `cd` does not persist between calls in a forked phase and `EnterWorktree` is not to be relied on there (shared rule 11). This phase records `implementation_sha` from HEAD, so reviewing from the wrong working directory would certify the wrong commit. Nothing printed means the feature has no worktree; continue here. Protocol: `${CLAUDE_PLUGIN_ROOT}/references/isolation.md`.

   **Then the branch guard, before reading a single diff.** Verify `git branch --show-current` is `sdd/<feature>` (or the branch `STATE.md` records). If it is not, **STOP** and report it — do not "fix" it with a checkout. `/sdd:run` has carried this guard since worktrees existed because it writes code; review needs it just as much because it *certifies*: `mark-ready` records `head_branch` and `implementation_sha` as the merge gate's evidence, and a review run from the base branch would sign a range that is not the change. Until now the conversation usually carried the right directory over from run; a phase that starts in a fresh context (shared rule 11) has only what it asks for.

   Then read the change's `proposal.md`, `design.md` (if any), and `tasks.md`. Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> review` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled). Without this mark, review's spend is attributed to whichever phase ran last.
2. **Launch the review panel in parallel** — every `Agent` call in a **single**
   assistant message, sent together: the three core reviewers — `sdd-architect`,
   `sdd-security`, `sdd-qa` — plus every project reviewer at
   `.claude/agents/sdd-review-*.md` (same discovery and contract as in `/sdd:run`).
   **In the foreground, and wait in this turn** (shared rule 11): this phase is
   a fork, and a fork that ends its turn is finished — no notification will
   wake it. Never launch reviewers in the background and never "pause until
   they report back": on the first real auto run this fork did exactly that and
   was ended with `sdd-qa` still running, so the verdict had to be rebuilt by
   the calling session.
   Launch `sdd-security` with `model: opus` here: its agent file defaults to
   Sonnet for the per-section panels of `/sdd:run`, and feature scale — the
   whole change, trust boundaries across sections — is where the stronger
   model earns its price.
   One call per message costs 2N round-trips of the most expensive context in the
   flow instead of 2, and lets each prompt be written after reading the previous
   verdict; `/sdd:run`'s step 3 has the measurement and the reasoning, including
   the rule that reviewers get their referents (R# text, quoted D#, quoted
   steering rules, diff range) **inline in the prompt** rather than going to find
   them.
   **Incremental scope — don't pay twice for what already PASSed**: read the `<!-- panel: PASS ... -->` annotations on `tasks.md` section headings first.
   - Sections **with** a PASS annotation: instruct the reviewers to NOT re-audit them line by line — for those, the scope is only what section-level review structurally can't see: interactions *between* sections, global design coherence (D# consistency across the whole change), and anything a later section changed in files an earlier PASSed section owned.
   - Sections **without** PASS (panel skipped, interrupted, or `solo` mode): full review scope, as if the section panel were running now.
   - Always at feature scale regardless of annotations: the R# completeness matrix (met/partially/unmet with `file:line` — qa) and cumulative scope creep.
   Give each reviewer the feature name, all requirement IDs, the annotation summary (which sections are pre-verified), and the full diff (or the file list if no git history delimits it).
3. **Synthesize**: merge the three reports, dedupe, and drop any finding without a referent (R#, D#, or quoted steering rule). Present per requirement: **met / partially met / unmet** with `file:line` of implementation and test (from the QA report), then the surviving findings most severe first, then scope creep.
4. Route the selected logical plan through the shared reviewer-panel boundary. An unavailable, malformed, incomplete, identity-mismatched, or out-of-scope result is an explicit non-passing result; never turn a degraded panel into certification by inline substitution.
4b. **When the verdict is FAIL, the fixes are not part of this phase — and they are
   not free either.** Review is report-only (see below), so fixing means leaving
   review and coming back. **Under `/sdd:auto`** the calling session is who comes
   back: fill the outcome object's `findings` (reviewer, severity, `file:line`,
   referent, what, fix direction — one item per surviving finding, nothing in
   prose that is not there) and end with `outcome: FAILED`; auto runs the fix
   ladder of its step 6 and re-invokes this skill. Two rules make that
   terminate, mirroring the fix loop `/sdd:run` already caps per section:
   - **Re-review what you fixed.** A finding closed without a reviewer seeing the
     fix is an unreviewed change wearing an approved verdict. Re-run only the
     reviewer(s) whose findings you touched, scoped to the fix.
   - **Two fix rounds, then stop and hand it to the user.** If a third round would
     be needed, say so and present what is open instead of iterating. Findings that
     keep reappearing in the same place are usually a structural problem — the same
     statement duplicated across several artifacts, a contract with no single home —
     and another round of edits will not fix that; naming it will. Record what is
     open with `sdd_lifecycle.py --root <path> block <feature> --phase review
     --type decision …` — never write `BLOCKED.md` by hand: the script derives the
     path from the change, and a fork that wrote it by hand left it at the
     worktree root (ADR 0006).
   - **An open `<!-- manual -->` task is not a FAIL.** If `mark-local-verified`
     refuses because a task marked `<!-- manual -->` is unchecked, record it as
     `deferred` naming the task (`block … --type deferred --task N.M --resume
     "/sdd:run <feature> N.M"`) and retry: `deferred` and `assumed` entries and
     the manual tasks they name travel with the PR, where the human performs the
     check; only `decision` entries stop `READY_FOR_PR`. An unchecked task
     **without** the marker is unfinished work and the refusal stands.
   Prefer verifying a text fix by grepping the superseded wording across the whole
   change, not by re-reading the passage you just rewrote: the corrected sentence
   tends to land in the explanatory copy while the stale one survives in the
   artifact that reaches the next implementer.
   **Any commit made to close findings invalidates the recorded
   `implementation_sha`** — re-run the lifecycle validation so the merge gate
   certifies the reviewed anchor and every later commit is an authorized
   STATE-only lifecycle commit. A later code/spec/evidence/metrics commit is
   drift and must be reviewed again; lifecycle metadata is not functional
   drift. When the change is already at `PR_OPEN`, the supported path is
   `/sdd:review <feature>` itself: step 5 below branches on `state == PR_OPEN`
   and calls `mark-recertified`, which re-anchors `implementation_sha` to the
   new reviewed HEAD on the same open PR. The user must `git push origin
   <head_branch>` (never `--force`) before invoking review in this case, so
   `mark-recertified` can verify the new HEAD is in the PR's `commits[]`.
5. Conclude with a verdict: locally verified or list what's missing. If the
   verdict passes, persist the lifecycle milestones. **Branch on `state`** —
   the change may already be at `PR_OPEN`, in which case the milestones below
   would be a no-op or an error:

   - `ACTIVE` or `LOCAL_VERIFIED` → the standard two-milestone sequence:

     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . mark-local-verified <feature>
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . mark-ready <feature> --base <target-base-branch>
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . validate-ship <feature>
     ```

   - `PR_OPEN` → recertification: launch the panel over the range
     `implementation_sha..HEAD` (the new fix, not the whole branch) and, on
     PASS, call:

     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . mark-recertified <feature>
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . validate-ship <feature>
     ```

     `mark-recertified` re-anchors `implementation_sha` to the parent SHA of
     the new lifecycle commit (the reviewed HEAD), preserves every PR
     identity field, refuses when the PR is `MERGED` or `CLOSED`, refuses
     when `HEAD` is not in the PR's `commits[]` (i.e. the user has not
     pushed), and never invokes `git push`. Validate-ship confirms the
     resulting suffix is lifecycle-only.

   Determine the target base from the current workflow/remote; if it is
   ambiguous, ask rather than guessing — **except under `/sdd:auto`**, which
   passes its recorded BASE explicitly and must never be interrupted with this
   question. The resulting `STATE.md` has
   `state: READY_FOR_PR` (or remains `PR_OPEN` after recertification),
   `local_review: APPROVED`, repository, branches, and the reviewed
   implementation SHA. This is not remote review, merge, spec fusion,
   roadmap completion, or archive.

   `mark-local-verified` persists `ACTIVE -> LOCAL_VERIFIED` as the first
   STATE-only lifecycle commit when the change's ACTIVE STATE is already in the
   implementation anchor. `mark-ready` then persists
   `LOCAL_VERIFIED -> READY_FOR_PR`; both transitions leave a clean worktree.
   `mark-recertified` (the recertification branch) persists the self-loop
   `PR_OPEN -> PR_OPEN` — the canonical state stays `PR_OPEN`, but the
   recorded `implementation_sha` advances to the reviewed HEAD on the same
   open PR; this is the supported path when a defect is found after the PR
   is opened.

6. **Metrics.** Run both unconditionally (each no-ops when tracking is off; NEVER
   skip them based on your own assessment of whether metrics are enabled):

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> review
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/usage-sync.py" --root . sync <feature>
   ```

   `sync` rebuilds every phase row from the captured log and refreshes the
   consolidated row in `sdd/metrics.md`, so a change waiting for its merge
   already has complete metrics instead of none until archive.

7. **Offer to publish — one question, not five instructions.** On a passing
   verdict, `READY_FOR_PR` is a change that is finished locally and invisible to
   everyone else: the branch is unpushed and no PR exists. End the turn with a
   `HANDOFF` (shared rule 11 — a forked phase cannot ask) whose single question
   is whether to run `/sdd:ship <feature>` now, recommending yes; the calling
   conversation asks it once and, on yes, runs `/sdd:ship <feature>`, which
   follows `${CLAUDE_PLUGIN_ROOT}/skills/ship/SKILL.md`.
   Ship stays a separate phase — review is report-only and must not grow a
   publishing contract — but *reaching* it should cost one tap, not a sequence
   of typed orders. If the user declines, `STATE.md` holds the next
   action and `/sdd:status` will keep surfacing it (shared rule 1).
   **Skip this question entirely under `/sdd:auto`**, which drives ship itself.

Do not fix findings in either mode. A passing change review may write the
lifecycle metadata above and the metrics ledger, and may hand off to
`/sdd:ship` with the user's explicit yes; all other review behavior remains
report-only.
