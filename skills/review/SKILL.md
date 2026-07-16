---
name: review
model: sonnet
description: Detect drift between sdd/specs/ and the code, or review an implemented change against its proposal before archiving. Use when the user runs /sdd-toolkit:review, asks whether specs are up to date, or wants a spec-vs-implementation check.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Review

Two modes, chosen by argument:

- no argument — **drift check**: compare `sdd/specs/` against the codebase.
- `<feature>` — **change review**: verify the implementation of `sdd/changes/<feature>/` against its proposal.

**Fallback when drift check would be vacuous:** if no argument was given and `sdd/specs/` is missing or empty, there's nothing to drift-check. If exactly one non-archived change exists in `sdd/changes/`, do a change review of it instead (say so explicitly). Otherwise, report that there's nothing to check yet and point to `/sdd-toolkit:new`.

## Drift check

1. Read `sdd/project.md` and every file in `sdd/specs/`.
2. For each spec requirement, verify the code still behaves that way (read the relevant code; run tests only if cheap).
3. Report a findings list, most severe first:
   - **Broken**: spec says X, code does Y.
   - **Undocumented**: significant behavior with no spec coverage.
   - **Stale**: spec references removed code/features.
4. Offer to update the affected spec files (with user approval, one file at a time).

## Change review

1. Read the change's `proposal.md`, `design.md` (if any), and `tasks.md`.
2. **Launch the review panel in parallel** (one message, three Agent calls — types `sdd-architect`, `sdd-security`, `sdd-qa`), scoped to the whole change: give each the feature name, all requirement IDs, and the full diff of the change (or the file list if no git history delimits it). This is the same panel `/sdd-toolkit:run` uses per section, now at feature scale — it catches what section-level review can't see (cross-section interactions, cumulative scope creep).
3. **Synthesize**: merge the three reports, dedupe, and drop any finding without a referent (R#, D#, or quoted steering rule). Present per requirement: **met / partially met / unmet** with `file:line` of implementation and test (from the QA report), then the surviving findings most severe first, then scope creep.
4. If a panel agent type isn't available, do its dimension yourself inline (degraded but complete).
5. Conclude with a verdict: ready to `/sdd-toolkit:archive`, or list what's missing.

Do not fix anything in either mode — report only, and let the user decide.
