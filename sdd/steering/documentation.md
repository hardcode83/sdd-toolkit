---
phases: [tasks, archive]
---

# Documentation

## What must stay updated

- Changes to lifecycle behavior update the relevant `sdd/specs/` capability
  document through the normal archive flow.
- Changes to Codex installation, invocation, or compatibility update `docs/codex.md`.
- Architectural decisions with lasting runtime or packaging consequences belong
  in `docs/adr/` and are referenced from the proposal/design.

## Audiences & locations

Users read `README.md`, `docs/guide.md`, `docs/codex.md`, and `docs/faq.md`.
Maintainers read `rules.md`, `references/`, executable tests, and ADRs.
Runtime behavior is documented by the SDD specs and lifecycle artifacts.

## Archive checklist

- [ ] User-facing installation and runtime behavior is documented.
- [ ] Affected living specs are updated by archive.
- [ ] Tests and fixtures describe the maintained contract.
