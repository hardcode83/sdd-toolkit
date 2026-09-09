# UI/UX review lens

## Purpose

The toolkit ships a first-class, specialized project reviewer for visual and
interactive surfaces — layout, typography, contrast, states, accessibility,
and consistency with a project's own design tokens and components. It is not
a fourth core reviewer: it is a project reviewer that the panel's existing
discovery, applicability, and fail-closed gate already support, and it runs
only on changes that touch visual surface.

## Requirements

### R1 — Specialized reviewer template

- The toolkit SHALL include `templates/reviewer-ui-ux.md` with valid
  frontmatter (`name`, `description`, `model`, `tools`, `phases`,
  `applies_to`) that passes `parse_frontmatter` in
  `scripts/validate_toolkit.py`.
- The template SHALL declare the panel's JSON result envelope
  (`reviewer_id`, `scope_id`, `lens`, `verdict`, `findings`, `evidence`,
  `status`) with `lens: ui-ux`, identical in shape to the core reviewers.
- The template SHALL enumerate twelve verifiable areas: layout/spacing/
  whitespace; visual hierarchy; typography; color/contrast/semantics;
  responsive/mobile; states (loading/empty/error/disabled/hover/focus);
  accessibility and keyboard navigation; consistency with design tokens and
  existing components; forms and interaction; density/readability of
  tables/dashboards; generic AI-generated UI patterns ("AI-tells"); and
  clarity of the primary action.
- The template SHALL ship with `phases: [run, review, auto]` and an
  illustrative `applies_to` already filled in, so an agent generated from it
  does not trigger `SDD028` (`scripts/sdd-doctor.py`).

### R2 — Methodology source and project steering

- The toolkit SHALL include `references/ui-ux-review.md`: an objective
  checklist covering the twelve areas plus a list of generic AI-generated UI
  patterns, each requiring observable evidence.
- `references/ui-ux-review.md` is a methodology source used to author and
  maintain the reviewer template and a project's frontend steering. It is
  NOT a referent category of the panel: a finding that cites only this
  document has no valid referent and MUST NOT be reported.
- The toolkit SHALL include `templates/steering/frontend.md`: a
  frontend/design-system steering template with `applies_to` frontmatter and
  sections for design tokens, components, states, responsive, and
  accessibility, carrying a minimal citable objective baseline (contrast,
  visible focus, keyboard access, interaction target size, essential
  states, responsive) derived from `references/ui-ux-review.md`.
- The steering template SHALL remain stack-agnostic: no hardcoded stack
  command (verified by `STACK_COMMAND_RE` in `scripts/validate_toolkit.py`)
  and no toolkit-owned artifact reference.
- WHEN `/sdd:init` materializes the UI/UX lens, THE SYSTEM SHALL guarantee a
  project frontend/design-system steering doc exists — creating it from the
  template if absent — so the lens always has a citable referent.
- The steering template and reviewer template SHALL NOT prescribe Apple,
  Material, or any other concrete brand aesthetic as a normative standard;
  the project's own steering remains the authority on aesthetic decisions.

### R3 — Selective activation via `/sdd:init`

- WHEN `/sdd:init` detects a relevant frontend/design-system surface, THE
  SYSTEM SHALL offer (never impose) generating the UI/UX lens as one of the
  project reviewer lenses listed in `skills/init/SKILL.md`.
- IF the user accepts, THEN THE SYSTEM SHALL generate
  `.claude/agents/sdd-review-ui-ux.md` from `templates/reviewer-ui-ux.md`
  and create the frontend/design-system steering if it does not already
  exist, with `applies_to` derived from the repo's actual frontend roots
  (not a fixed list).
- WHEN `/sdd:init` offers this lens alongside the `frontend-design` plugin,
  THE SYSTEM SHALL reaffirm the documented overlap
  (`references/plugin-catalog.md`): `frontend-design` pushes toward a
  distinctive look; this lens verifies consistency; the project's steering
  wins over either's taste.
- The generated agent's frontmatter SHALL include `phases` and `applies_to`
  such that `/sdd:doctor` does not report `SDD028` against it.
- IF `/sdd:init` cannot reliably determine the project's frontend roots,
  THEN THE SYSTEM SHALL surface the ambiguity (e.g. via `AskUserQuestion`)
  instead of silently generating a broad, guessed, or misleading
  `applies_to`.

### R4 — MATCH only on visual surface, planner unchanged

- WHEN a section's or feature's scope includes at least one file matching
  the lens's `applies_to`, THE SYSTEM SHALL plan the lens as `MATCH` and run
  it, using the existing `build_reviewer_plan`/`evaluate_applicability`
  logic unchanged.
- WHEN the scope includes no file matching the lens's `applies_to`, THE
  SYSTEM SHALL record the lens as `skipped` (definitive NO MATCH), never
  silently omitted.
- WHILE the lens's `phases`/`applies_to` metadata is missing or unevaluable,
  THE SYSTEM SHALL treat it as `UNKNOWN` and run it (fail-safe), matching
  existing planner semantics.
- This SHALL be achieved without editing
  `skills/reviewer-panel/reviewer_plan.py` or `scripts/reviewer_panel.py`.

### R5 — Objective, actionable, referent-backed findings

- The template SHALL instruct referent-or-discard discipline: a finding
  with no referent MUST NOT be reported. The only valid panel referents are
  a quoted project steering rule, an R#, or a D#; a toolkit methodology
  source such as `references/ui-ux-review.md` is never itself a referent.
  This lens does not widen the panel's existing referent contract.
- WHEN the project has frontend/design-system steering, THE SYSTEM SHALL
  verify against that steering and the project's real tokens/components,
  citing the steering rule (or an R#/D#) as referent — never a toolkit
  aesthetic.
- IF the project lacked sufficient frontend/design-system steering, THEN THE
  SYSTEM SHALL rely on the objective baseline that `/sdd:init` seeds (R2) as
  a citable referent; concrete evidence (e.g. a contrast ratio, missing
  focus state, missing state, duplicated component) demonstrates the
  violation but never substitutes for the referent itself.
- WHEN the lens reports a generic AI-generated UI pattern, THE SYSTEM SHALL
  require observable evidence in the code or design in scope, never a taste
  judgment.

### R6 — Panel invariants preserved

- This lens SHALL NOT require changes to
  `skills/reviewer-panel/reviewer_plan.py`, `scripts/reviewer_panel.py`, the
  three core reviewer JSON definitions, or the three core `agents/sdd-*.md`
  files.
- After adding this lens, THE SYSTEM SHALL still validate that the core
  registry contains exactly `sdd-architect`, `sdd-security`, and `sdd-qa`
  (`python3 scripts/validate_toolkit.py all`).
- IF a result from this lens is unavailable, malformed, or out of scope,
  THEN THE SYSTEM SHALL still fail closed at the existing panel gate
  (`evaluate_panel_gate`), with no inline substitution.
- Receipt and `--carry` behavior SHALL remain unchanged when this lens is
  present in the plan.

## Key files

- `templates/reviewer-ui-ux.md` — the specialized reviewer template shipped
  by the toolkit.
- `references/ui-ux-review.md` — the toolkit's objective UI/UX methodology
  source (never a panel referent).
- `templates/steering/frontend.md` — the frontend/design-system steering
  template with the citable objective baseline.
- `skills/init/SKILL.md` — offers and materializes the lens plus its
  steering during `/sdd:init`.
- `skills/reviewer-panel/reviewer_plan.py` — unchanged; discovers, plans,
  and applies MATCH/NO MATCH/UNKNOWN semantics to this lens like any other
  project reviewer.
- `tests/test_reviewer_plan.py`, `tests/test_reviewer_results.py`,
  `tests/test_toolkit_validation.py`, `tests/test_sdd_doctor.py`,
  `tests/test_panel_receipt.py` — cover MATCH/NO MATCH, fail-closed
  behavior, artifact conformance, `SDD028`, and receipts/`--carry` with this
  lens present.
