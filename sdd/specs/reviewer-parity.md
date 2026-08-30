# Reviewer panel parity

## Purpose

The SDD review panel has one logical reviewer plan shared by Claude and Codex.
Runtime adapters may differ in invocation mechanics, but they must preserve
reviewer coverage, scope, identity, and the fail-closed certification boundary.

## Requirements

### R1 — Shared reviewer selection

- The required core panel always includes exactly `sdd-architect`,
  `sdd-security`, and `sdd-qa`.
- Project reviewers found at `.claude/agents/sdd-review-*.md` are additive for
  both runtimes and retain their project-owned lens and criteria.
- A missing, malformed, duplicate, unsafe, or unresolved reviewer is
  unavailable and cannot be treated as a passing review or suppress another
  reviewer.

### R2 — Canonical definitions and applicability

- Core reviewer identity, lens, read-only contract, criteria, and referents are
  defined once in the packaged reviewer registry.
- Repository-local project reviewers accept the documented union of Claude
  legacy fields (`name`, `description`, `model`, `tools`) and planner metadata
  (`phases`, `applies_to`), including legacy-only, new-only, and mixed forms.
- Claude `model` and `tools` remain provider-specific declarations; Codex uses
  the reviewer body, identity, scope, and toolkit-owned read-only contract
  without treating them as Codex capabilities.
- Project reviewer applicability reuses the existing `phases` and `applies_to`
  matching semantics for `run`, `review`, and `auto`.
- `MATCH` and `UNKNOWN` project reviewers run; only definitive `NO MATCH` may
  be skipped, with the decision and reason retained in the plan.
- Malformed or unevaluable applicability metadata remains `UNKNOWN` and
  runnable rather than becoming a definitive skip.
- Core reviewers are unconditional wherever the lifecycle requires a panel.

### R3 — Runtime adapter parity

- Claude and Codex consume the same ordered logical plan, exact feature scope,
  and reviewer identities.
- Claude uses its existing agent compatibility path. Codex uses the top-level
  harness for one parallel native-subagent batch, trusted handle-to-reviewer
  binding, waiting, and raw result collection.
- The installed Codex plugin contains the planner, validator, registry, and
  prompts without requiring copied agents, symlinks, or project Codex setup.

### R4 — Structured fail-closed results

- Each runnable reviewer produces exactly one result bound to its planned
  reviewer identity and scope.
- A result has a `PASS` or `FAIL` verdict, list-valued findings and evidence,
  and complete collection status. `FAIL` requires a finding; `PASS` requires
  verifiable evidence within scope.
- Missing, unavailable, timed-out, interrupted, malformed, incomplete,
  duplicate, spoofed, identity-mismatched, or out-of-scope results fail the
  panel gate. The panel passes only when every required runnable reviewer
  passes and the core invariant holds.

### R5 — Lifecycle boundary

Only a validated passing panel may authorize the existing review certification
sequence. The panel normalizer does not write `STATE.md`, add lifecycle states,
or create telemetry. `PR_OPEN` review remains anchored to
`implementation_sha..HEAD` and uses the existing recertification and ship
guards documented in `ship-and-review-contract.md`.

## Verification

The repository's reviewer-plan, result, adapter, parity, packaging, and smoke
tests derive expected reviewer identities from the registry and cover core
coverage, applicability, legacy project reviewers, parallel dispatch,
fail-closed result handling, and unchanged repository state.
