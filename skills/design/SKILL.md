---
name: design
model: opus
description: Write the technical design for an SDD change (sdd/changes/<feature>/design.md) - decisions, affected files, risks. Use when the user runs /sdd-toolkit:design after the proposal is approved.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Design

Write the technical design for a change. Argument: the feature name; if omitted and exactly one non-archived change exists in `sdd/changes/`, use it — otherwise ask.

## Steps

1. **Load context.** Read `sdd/project.md`, the change's `proposal.md`, and any `sdd/specs/` files it lists as affected. If there is no proposal, stop and point to `/sdd-toolkit:new`. Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> design` (silent no-op if tracking is disabled).
   - **Steering**: if `sdd/steering/` exists, read each doc's frontmatter and fully load those whose `phases` (if present) include `design` and whose `applies_to` (if present) matches the proposal's scope. `architecture.md` and `security.md` rules are binding here — a design that needs to break one must say so explicitly as an open question, never silently.
2. **Triviality check.** If the change needs no real design decisions (obvious approach, few files, no new dependencies or data changes), say so and recommend skipping straight to `/sdd-toolkit:tasks` instead of producing a ceremonial document. Only continue if the user insists or the change warrants it.
3. **Investigate the code** the change touches: current structure, patterns to follow, integration points. Design must fit the existing codebase, not an idealized one.
4. **Write** `sdd/changes/<feature>/design.md` using `${CLAUDE_PLUGIN_ROOT}/templates/design-template.md`. Rules:
   - Every decision states the chosen option **and why**, with rejected alternatives one line each.
   - Reference real files/modules with paths.
   - Cover every requirement in the proposal — if a requirement has no design implication, say so explicitly.
   - Surface **open questions** rather than silently deciding on things the user should weigh in on.
   - No code beyond short illustrative snippets or interface signatures.
   - If a visual would say it better (flows, state machines, component interactions), generate it with the `sdd-toolkit:diagram` skill and reference the PNG from the design doc.
5. **Metrics.** Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> design` (silent no-op if tracking is disabled).
6. **Gate.** Summarize the key decisions and open questions, resolve the open questions with the user (AskUserQuestion when they are concrete choices), and wait for approval. Then suggest `/sdd-toolkit:tasks`.
