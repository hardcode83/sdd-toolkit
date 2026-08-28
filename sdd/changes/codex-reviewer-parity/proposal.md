# Proposal: codex-reviewer-parity

## Why

The toolkit documents the Codex adapter as sharing the SDD lifecycle, but its
reviewer-panel support is currently described as unsupported. This leaves
review and certification dependent on Claude-only dispatch and can silently
reduce assurance for Codex users. The change makes reviewer selection,
execution, and fail-closed certification equivalent at the Codex boundary
without maintaining a second methodology.

## What changes

Define one logical reviewer plan and minimal result contract for the supported
panel paths. Preserve the existing Claude agent mechanism and
`.claude/agents/sdd-review-*.md` compatibility, add a thin Codex native
subagent adapter distributed by the Codex plugin, reuse `phases`/`applies_to`
for project-reviewer applicability, and add mechanically derived parity and
packaging tests.

## Requirements

### R1 — Runtime-independent reviewer selection

**As a** toolkit maintainer, **I want** reviewer selection to occur before
runtime invocation, **so that** runtime choice cannot change review coverage.

Acceptance criteria:

1. WHEN a supported core panel is required, THE SYSTEM SHALL select all three
   mandatory logical reviewers: `sdd-architect`, `sdd-security`, and `sdd-qa`.
2. WHEN a project contains `.claude/agents/sdd-review-*.md`, THE SYSTEM SHALL
   discover each valid project reviewer as an additive logical reviewer for
   both Claude and Codex without requiring immediate migration.
3. IF any mandatory or applicable logical reviewer cannot be resolved or
   invoked, THEN THE SYSTEM SHALL report it as unavailable and SHALL NOT claim
   a complete or passing review.

### R2 — One logical source and thin runtime adapters

**As a** toolkit maintainer, **I want** each reviewer’s identity and criteria
to have one canonical source, **so that** Claude and Codex definitions cannot
drift.

Acceptance criteria:

1. WHEN a core or project reviewer is defined, THE SYSTEM SHALL expose one
   canonical logical definition for its stable name, criteria, read-only
   contract, and applicable phases/areas.
2. WHEN Claude or Codex invokes a reviewer, THE SYSTEM SHALL use the canonical
   definition through a thin or mechanically derived adapter, not an
   independently maintained methodology copy.
3. THE SYSTEM SHALL mechanically detect missing, duplicate, renamed, or
   divergent runtime representations before they can omit a reviewer.

### R3 — Native Codex execution and plugin distribution

**As a** Codex user, **I want** the installed SDD plugin to provide reviewer
execution automatically, **so that** no manual agent setup is required.

Acceptance criteria:

1. WHEN Codex runs a supported panel, THE SYSTEM SHALL spawn the selected
   logical reviewers as native Codex subagents, in parallel, and SHALL wait for
   and collect results with reviewer identity preserved.
2. Codex reviewer execution SHALL enforce the existing read-only reviewer
   contract within the feature worktree; if that boundary or result collection
   cannot be enforced, THE SYSTEM SHALL fail visibly before certification.
3. WHEN the SDD Codex plugin is installed or updated, THE SYSTEM SHALL contain
   all resources required for its adapter; users SHALL NOT need
   `~/.codex/agents`, copied prompts, symlinks, or project-local Codex config.
4. The Claude plugin and existing Claude agent paths SHALL remain supported;
   MiniMax-through-Claude SHALL continue through the same Claude path.

### R4 — Fail-safe project-reviewer applicability

**As a** project maintainer, **I want** irrelevant project reviewers to be
skipped only when non-applicability is proven, **so that** efficiency cannot
reduce assurance.

Acceptance criteria:

1. WHEN applicability is evaluated, THE SYSTEM SHALL reuse the existing
   `phases` and `applies_to` matching semantics rather than create a second
   matching language.
2. WHEN applicability is MATCH, THE SYSTEM SHALL run the reviewer; WHEN it is
   UNKNOWN, including missing metadata, THE SYSTEM SHALL run it; WHEN it is a
   definitive NO MATCH, THE SYSTEM MAY skip it and SHALL retain the decision
   for the dispatch result.
3. Applicability SHALL never apply to the mandatory core reviewers, which are
   unconditional wherever the current lifecycle requires the panel.
4. A malformed, duplicate, unsafe, or otherwise unresolved project reviewer
   definition SHALL not suppress another reviewer or turn the panel into PASS.

### R5 — Minimal structured, fail-closed results and lifecycle parity

**As a** lifecycle gate, **I want** collected results validated before
acceptance, **so that** incomplete output cannot become PASS.

Acceptance criteria:

1. WHEN a reviewer completes, THE SYSTEM SHALL validate a minimal result with
   expected reviewer identity/lens, `PASS` or `FAIL` verdict, findings,
   evidence/referents, and collection status; unexpected, duplicate, or
   spoofed identities SHALL be rejected.
2. IF a result is missing, unavailable, timed out, interrupted, malformed,
   incomplete, identity-mismatched, or outside the reviewed scope, THEN THE
   SYSTEM SHALL fail closed, identify the reason, and SHALL NOT advance
   lifecycle state or record approval evidence.
3. WHEN every required result passes, `ACTIVE`/`LOCAL_VERIFIED` SHALL use the
   existing standard certification sequence; `PR_OPEN` SHALL review
   `implementation_sha..HEAD`, preserve its push/branch guards, use
   `mark-recertified`, and pass `validate-ship` as currently specified.
4. Result normalization SHALL not add a telemetry platform, event graph,
   token ledger, or unrelated lifecycle-state transition. Existing
   `STATE.md` schema-1 and section PASS/selector semantics remain valid.

### R6 — Mechanical parity and regression coverage

**As a** toolkit maintainer, **I want** tests derived from the logical reviewer
plan, **so that** runtime adapters cannot silently diverge.

Acceptance criteria:

1. Tests SHALL derive the expected reviewer plan from the canonical definitions
   and compare Claude/Codex logical sets for equivalent run, review, and
   applicable auto dispatch inputs.
2. Tests SHALL prove core roles cannot be skipped; project MATCH and UNKNOWN
   run; definitive NO MATCH may skip; legacy `.claude/agents/sdd-review-*.md`
   projects remain compatible; and selected panels remain parallel.
3. Tests SHALL cover valid PASS, FAIL, missing, unavailable, timeout,
   malformed, incomplete, duplicate, identity-mismatched, and out-of-scope
   results, asserting lifecycle non-advancement and read-only policy on failure.
4. Tests SHALL validate Claude and Codex plugin packaging and an opt-in native
   Codex smoke path (parallel spawn, wait, role identity, result collection,
   no repository mutation) without making paid model execution mandatory.

## Out of scope

- A generic provider framework or independently maintained Claude/Codex
  reviewer prompts.
- New reviewer roles or immediate consumer-project migration.
- Telemetry platforms, extensive event IDs, token ledgers, dashboards,
  context hashes, cheaper-model routing, lower reasoning effort, or aggressive
  context slicing.
- Removing mandatory core reviewers, reducing QA execution, or weakening
  lifecycle/merge gates.
- Unrelated lifecycle transitions, application/domain behavior, or tournament
  orchestration beyond documenting its separate treatment.
- Running design, tasks, implementation, review, ship, merge, or archive in
  this proposal phase.

## Affected specs

- `sdd/specs/ship-and-review-contract.md` — preserve and cross-reference the
  existing state-dependent certification contract.
- `sdd/specs/reviewer-parity.md` *(no existe aún — se creará al archivar)* —
  logical reviewer plan, adapters, applicability, and result contract.
- `docs/codex.md` — Codex reviewer support, packaging, and compatibility matrix.
