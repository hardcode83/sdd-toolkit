---
name: review
model: sonnet
description: Detect drift between sdd/specs/ and code, or validate an implemented change locally and mark it READY_FOR_PR. Use when the user runs /sdd:review, asks whether specs are up to date, or wants a spec-vs-implementation check.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Review

Two modes, chosen by argument:

- no argument — **drift check**: compare `sdd/specs/` against the codebase.
- `<feature>` — **change review**: verify the implementation of `sdd/changes/<feature>/` against its proposal.

**Fallback when drift check would be vacuous:** if no argument was given and `sdd/specs/` is missing or empty, there's nothing to drift-check. If exactly one non-archived change exists in `sdd/changes/`, do a change review of it instead (say so explicitly). Otherwise, report that there's nothing to check yet and point to `/sdd:new`.

## Drift check

1. Read `sdd/project.md` and every file in `sdd/specs/`.
2. For each spec requirement, verify the code still behaves that way (read the relevant code; run tests only if cheap).
3. Report a findings list, most severe first:
   - **Broken**: spec says X, code does Y.
   - **Undocumented**: significant behavior with no spec coverage.
   - **Stale**: spec references removed code/features.
4. Offer to update the affected spec files (with user approval, one file at a time).

## Change review

0. **Prefer a fresh session** (shared rule 11). Everything this phase needs —
   proposal, design, tasks, the diff, `STATE.md` — is on disk, and it is the most
   expensive phase per request in the flow (571k of context on average in the
   measured corpus) precisely because it usually runs on top of a long `/sdd:run`.
   If the session already carries the implementation it is about to review, say
   so once and recommend `/clear`; then continue either way — this is advice, not
   a gate.

1. **Worktree first** (shared rule 10): `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . resolve <feature>`. If it prints a path that is not the current directory, enter it with `EnterWorktree` (`path`) — this phase records `implementation_sha` from HEAD, so reviewing from the wrong working directory would certify the wrong commit. Nothing printed means the feature has no worktree; continue here. Protocol: `${CLAUDE_PLUGIN_ROOT}/references/isolation.md`.

   Then read the change's `proposal.md`, `design.md` (if any), and `tasks.md`. Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> review` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled). Without this mark, review's spend is attributed to whichever phase ran last.
2. **Launch the review panel in parallel** — every `Agent` call in a **single**
   assistant message, sent together: the three core reviewers — `sdd-architect`,
   `sdd-security`, `sdd-qa` — plus every project reviewer at
   `.claude/agents/sdd-review-*.md` (same discovery and contract as in `/sdd:run`).
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
4. If a panel agent type isn't available, do its dimension yourself inline (degraded but complete).
4b. **When the verdict is FAIL, the fixes are not part of this phase — and they are
   not free either.** Review is report-only (see below), so fixing means leaving
   review and coming back. Two rules make that terminate, mirroring the fix loop
   `/sdd:run` already caps per section:
   - **Re-review what you fixed.** A finding closed without a reviewer seeing the
     fix is an unreviewed change wearing an approved verdict. Re-run only the
     reviewer(s) whose findings you touched, scoped to the fix.
   - **Two fix rounds, then stop and hand it to the user.** If a third round would
     be needed, say so and present what is open instead of iterating. Findings that
     keep reappearing in the same place are usually a structural problem — the same
     statement duplicated across several artifacts, a contract with no single home —
     and another round of edits will not fix that; naming it will.
   Prefer verifying a text fix by grepping the superseded wording across the whole
   change, not by re-reading the passage you just rewrote: the corrected sentence
   tends to land in the explanatory copy while the stale one survives in the
   artifact that reaches the next implementer.
   **Any commit made to close findings invalidates the recorded
   `implementation_sha`** — re-run `mark-ready` (it re-records when HEAD moved) so
   the merge gate certifies the fixed range and not the one that failed.
5. Conclude with a verdict: locally verified or list what's missing. If the
   verdict passes, persist the two explicit lifecycle milestones:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . mark-local-verified <feature>
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . mark-ready <feature> --base <target-base-branch>
   ```

   Determine the target base from the current workflow/remote; if it is
   ambiguous, ask rather than guessing — **except under `/sdd:auto`**, which
   passes its recorded BASE explicitly and must never be interrupted with this
   question. The resulting `STATE.md` has
   `state: READY_FOR_PR`, `local_review: APPROVED`, repository, branches, and
   the reviewed implementation SHA. This is not remote review, merge, spec
   fusion, roadmap completion, or archive.

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
   everyone else: the branch is unpushed and no PR exists. Ask once
   (`AskUserQuestion`, recommend yes) whether to run `/sdd:ship <feature>` now,
   and if the user accepts, follow `${CLAUDE_PLUGIN_ROOT}/skills/ship/SKILL.md`.
   Ship stays a separate phase — review is report-only and must not grow a
   publishing contract — but *reaching* it should cost one tap, not a sequence
   of typed orders. If the user declines, say that `STATE.md` holds the next
   action and `/sdd:status` will keep surfacing it (shared rule 1).
   **Skip this question entirely under `/sdd:auto`**, which drives ship itself.

Do not fix findings in either mode. A passing change review may write the
lifecycle metadata above and the metrics ledger, and may hand off to
`/sdd:ship` with the user's explicit yes; all other review behavior remains
report-only.
