---
phases: [tasks, run]
---

# Testing

## Test types and when

- Python lifecycle, registry, doctor, validation, and contract behavior uses
  the repository's `unittest` suite.
- Fixture-driven validation covers malformed and boundary project layouts.
- Skill and plugin changes require deterministic contract tests; runtime
  integration tests should be opt-in when they require external models.
- Changes crossing Claude/Codex dispatch boundaries require mechanically
  derived parity tests and read-only native Codex smoke coverage where practical.

## Conventions

Tests live under `tests/`, use standard-library tooling, and import scripts by
the existing test path conventions. Fixtures must be explicit about expected
validity and must not mutate the source repository.

## Coverage & quality bars

Preserve mandatory gates, fail-closed behavior, reviewer identity, and existing
lifecycle semantics. A token or call reduction is not an improvement if it
changes reviewer coverage or gate results.

## Commands

Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v`; for the CI
contract subsets use the exact `scripts/validate_toolkit.py` commands recorded
in `sdd/project.md`.
