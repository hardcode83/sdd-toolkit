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

1. Read the change's `proposal.md`, `design.md` (if any), and `tasks.md`. Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> review` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled). Without this mark, review's spend is attributed to whichever phase ran last.
2. **Launch the review panel in parallel** (one message, one Agent call per reviewer): the three core reviewers — `sdd-architect`, `sdd-security`, `sdd-qa` — plus every project reviewer at `.claude/agents/sdd-review-*.md` (same discovery and contract as in `/sdd:run`).
   **Incremental scope — don't pay twice for what already PASSed**: read the `<!-- panel: PASS ... -->` annotations on `tasks.md` section headings first.
   - Sections **with** a PASS annotation: instruct the reviewers to NOT re-audit them line by line — for those, the scope is only what section-level review structurally can't see: interactions *between* sections, global design coherence (D# consistency across the whole change), and anything a later section changed in files an earlier PASSed section owned.
   - Sections **without** PASS (panel skipped, interrupted, or `solo` mode): full review scope, as if the section panel were running now.
   - Always at feature scale regardless of annotations: the R# completeness matrix (met/partially/unmet with `file:line` — qa) and cumulative scope creep.
   Give each reviewer the feature name, all requirement IDs, the annotation summary (which sections are pre-verified), and the full diff (or the file list if no git history delimits it).
3. **Synthesize**: merge the three reports, dedupe, and drop any finding without a referent (R#, D#, or quoted steering rule). Present per requirement: **met / partially met / unmet** with `file:line` of implementation and test (from the QA report), then the surviving findings most severe first, then scope creep.
4. If a panel agent type isn't available, do its dimension yourself inline (degraded but complete).
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

Do not fix findings in either mode. A passing change review may write the
lifecycle metadata above and the metrics ledger; all other review behavior
remains report-only.
