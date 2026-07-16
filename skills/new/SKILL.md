---
name: new
model: opus
description: Start a new SDD change - creates sdd/changes/<feature>/proposal.md with the why, scope, and EARS requirements. Use when the user runs /sdd:new or asks to spec out a feature.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — New

Create a change proposal. Arguments: the feature name — normalize to kebab-case (e.g. `user-auth`) — plus an optional **requirements/seed document** (a path to a markdown file, e.g. `/sdd:new user-auth docs/reqs-auth.md`). If no argument was given: if `sdd/roadmap.md` exists, propose taking its first unchecked entry; otherwise derive a short name from the user's description and confirm it.

**Seed document** (from the argument, or referenced as `fuente:` in the roadmap entry): read it and use it as the source of truth for requirements — but **convert, don't copy**: restate its requirements as numbered user stories with EARS criteria, flag anything ambiguous or untestable as written (those become your questions in step 2, or explicit `ASSUMPTION`s), flag anything that contradicts `product.md`/existing specs, and note what the doc leaves out (error cases, limits). Link the doc from the proposal's Why section. A good seed doc makes step 2 unnecessary — that's what makes it ideal for `/sdd:auto`.

## Steps

1. **Load context.** Read `sdd/project.md` and skim `sdd/specs/` for capabilities this change touches. If `sdd/` doesn't exist, tell the user to run `/sdd:init` first and stop. Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> new` (silent no-op if tracking is disabled).
   - **Claim check** (only if the repo has a git remote): `git ls-remote --heads origin "sdd/<feature>"`. If the branch exists, someone is already working this feature — report it (after `git fetch origin sdd/<feature>`, show `git log -1 --format='%an %ad %s'` of it) and STOP unless the user explicitly says to continue anyway. If it's clear, **offer to create and push the claim branch** `sdd/<feature>` before writing anything — the remote branch IS the team's lock (recommended in shared repos; skip for solo/trunk workflows if the user prefers).
   - **Steering**: if `sdd/steering/` exists, read each doc's frontmatter and fully load those whose `phases` (if present) include `new` and whose `applies_to` (if present) matches the areas the request describes. A proposal must respect `product.md` principles when that doc exists — if the request conflicts with them, raise it before writing.
   - **Roadmap**: if the feature comes from `sdd/roadmap.md`, use its line (and source reference) as the seed, and mark the entry as started by appending ` → changes/<feature>/`.
2. **Understand the ask.** If the request is ambiguous on something that changes the requirements (not implementation details), ask the user 1-3 targeted questions (AskUserQuestion). Otherwise proceed.
   - **Adopting in-flight work**: if the feature is already partially built (the user says so, or the code clearly shows it), the proposal documents the *intended end state* as usual — reality is captured later, when `/sdd:tasks` pre-checks what's already done.
3. **Write** `sdd/changes/<feature>/proposal.md` using `${CLAUDE_PLUGIN_ROOT}/templates/proposal-template.md`. Rules:
   - Requirements are user stories with **EARS acceptance criteria** ("WHEN <trigger>, THE SYSTEM SHALL <response>"; also WHILE/WHERE/IF-THEN as needed). Each criterion must be objectively verifiable.
   - Number requirements (R1, R2…) — tasks will reference them later.
   - 3-7 requirements for a typical change. If you need more, the change is too big: propose splitting it.
   - An explicit **Out of scope** section — this is what keeps changes small.
   - In **Affected specs**, list the `sdd/specs/` files this change will touch. Flag the ones that don't exist yet with *(no existe aún — se creará al archivar)* — that's expected in adopted/brownfield projects, not a blocker.
   - Do NOT create `design.md` or `tasks.md`, and do not write any code.
4. **Metrics.** Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> new` (silent no-op if tracking is disabled).
5. **Gate.** Present a short summary and ask the user to review. On approval, suggest the next step: `/sdd:design` — or `/sdd:tasks` directly if the change is trivial (no new architecture, few files, obvious approach).
