---
name: history
model: sonnet
description: Query the project's SDD archive - timeline of completed changes, the full record of one change (decisions, rejected alternatives, cost, commits), or free-form questions about why things are the way they are, answered with citations and a validity check. Use when the user runs /sdd:history or asks why a past decision was made, what a past change did, or what has shipped.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — History

Query the project's decision record. Read-only — change nothing. The sources, in order of authority:

1. `sdd/changes/archive/<date>-<feature>/` — proposal (the why), design (decisions **and rejected alternatives**), tasks (what was actually done), metrics (what it cost), BLOCKED.md (what got stuck and how it was resolved).
2. `sdd/specs/` and `sdd/steering/` — the *current* truth, used to check whether a past decision still stands.
3. `git log` — correlated commits (auto-mode commits are prefixed `sdd(<feature>):`; otherwise search by file paths or feature name).

**Citation contract**: every claim cites its source (`archive/2026-07-15-infra-scaffold/design.md, D2` or a commit hash). No source → say you couldn't find it; never reconstruct history from plausibility.

## Modes (by argument)

### No argument — timeline

List archived changes chronologically (folder date prefix): date · feature · one-line what it did (from the proposal's Why/What) · capabilities/specs it touched · cost (from `metrics.md`, if present). End with totals (changes shipped, cumulative cost if tracked). This looks backward; point to `/sdd:status` for what's ahead.

### `<feature>` — one change's full record

Present the change's ficha:

- **Why & what** — proposal summary, requirements count, out-of-scope choices.
- **Decisions** — each D# from design.md: what was chosen, why, and what was rejected. If there was no design.md, say so (trivial change — thin record by design).
- **Execution** — task sections completed, anything noted `(preexistente)`, deviations recorded, BLOCKED episodes if any.
- **Cost** — per-phase table from metrics.md if present.
- **Commits** — `git log --oneline --grep "sdd(<feature>)"`, falling back to `git log --oneline -- <paths it touched>` for manually-driven changes.
- **Still standing?** — check the change's spec updates against current `sdd/specs/`: note anything a later change modified (cite which).

### `<free-form question>` — decision archaeology

For questions like "why is infra organized by environment?" or "did we ever consider X?":

1. Search the archive (proposals, designs — especially rejected alternatives — and BLOCKED files), then steering docs (standing decisions sections), then git log messages.
2. Answer with the decision, its context at the time, and the citation(s).
3. **Validity check** — always state whether the decision still stands: contrast with current specs/steering and later archived changes. Label it `vigente`, `superada por <change>` (cite), or `parcialmente vigente` (explain the delta).
4. If nothing is found, say so plainly and list where you looked — an absent record is a finding, not a license to guess.

Answer in the language the user communicates in.
