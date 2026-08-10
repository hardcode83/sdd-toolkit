# Proposal: SDD Toolkit 0.33 lifecycle integrity

## Why

During the P2 review, Toolkit 0.33 exposed an inconsistent lifecycle contract:
`mark-ready` writes `STATE.md` after capturing `HEAD`, while review/QA can require
a clean worktree and ship requires `HEAD == implementation_sha`. The shipped
`record-pr` implementation also writes metadata but does not perform the commit
described by the ship skill. This change targets the Toolkit implementation and
its skills/tests only; it does not change AgentsLabs application semantics.

## What changes

Define one auditable lifecycle model in which implementation identity is a
stable reviewed commit and lifecycle metadata is persisted by an explicit,
non-self-referential operation. Align `mark-ready`, review, ship, `record-pr`,
the worktree policy, scripts and automated tests so a lifecycle-only update
cannot create an unreviewed-range or self-SHA loop.

## Requirements

### R1 — Stable implementation identity

**As a** maintainer, **I want** `implementation_sha` to identify the reviewed
implementation range independently of later lifecycle metadata, **so that**
metadata persistence cannot invalidate its own identity.

Acceptance criteria:

1. WHEN `mark-ready` runs at a reviewed HEAD, THE SYSTEM SHALL record a stable
   implementation identity and an explicit lifecycle metadata version/commit
   model without requiring `STATE.md` to contain its own future SHA.
2. IF lifecycle metadata is persisted in a later commit, THEN THE SYSTEM SHALL
   preserve the reviewed implementation identity and SHALL make the later
   lifecycle commit auditable as metadata-only.

### R2 — Consistent clean-worktree policy

**As a** reviewer, **I want** review and ship to apply the same documented
worktree policy, **so that** QA cannot reject a state that ship is designed to
consume.

Acceptance criteria:

1. WHEN review completes, THE SYSTEM SHALL report whether lifecycle metadata is
   pending and SHALL apply the declared clean/dirty policy consistently.
2. IF a clean worktree is required for handoff, THEN THE SYSTEM SHALL provide
   an official persistence operation that reaches clean state without changing
   the reviewed implementation identity.

### R3 — End-to-end lifecycle operations

**As a** change owner, **I want** `mark-ready`, `record-pr` and ship to share one
   contract, **so that** READY_FOR_PR and PR_OPEN remain objectively verifiable.

Acceptance criteria:

1. WHEN ship verifies a READY_FOR_PR change, THE SYSTEM SHALL validate the
   declared implementation identity and lifecycle metadata according to the
   same model used by review.
2. WHEN `record-pr` persists PR evidence, THE SYSTEM SHALL create an explicit
   commit containing only the feature's lifecycle metadata and SHALL NOT push;
   push SHALL remain exclusively the responsibility of `ship`.
3. IF a lifecycle-only commit follows implementation, THEN tests SHALL prove
   that ship neither publishes an unreviewed implementation range nor requires
   an impossible self-referential SHA.

### R4 — Reproducible regression coverage

**As a** Toolkit maintainer, **I want** automated lifecycle tests, **so that**
   future changes cannot reintroduce the contradiction.

Acceptance criteria:

1. Tests SHALL cover `mark-ready`, review, ship, `record-pr`, dirty and clean
   worktrees, coherent `implementation_sha`, and lifecycle-only commits.
2. Each test SHALL assert the relevant state, HEAD, exit code and filesystem
   cleanliness/dirtyness rather than relying on prose output alone.

### R5 — Scope and auditability

**As a** AgentsLabs maintainer, **I want** the fix isolated to Toolkit lifecycle
   governance, **so that** application behavior and unrelated changes remain
   protected.

Acceptance criteria:

1. WHEN the change is implemented, THE SYSTEM SHALL modify only Toolkit scripts,
   skills, lifecycle tests and the explicitly affected governance documentation.
2. THE SYSTEM SHALL preserve a trace from each lifecycle rule to its test and
   evidence, including the lifecycle-only commit case.

## Out of scope

- AgentsLabs application/domain behavior, P2, P3 and archived changes.
- Any relaxation of the ship gate without an explicit, tested replacement.
- Reset, amend, rebase, squash or history rewriting as a workaround.
- PR creation, merge, archive and remote policy changes.
- Implementing the fix in this proposal phase.

## Affected specs

- `README.md`
- `docs/guide.md`
- Toolkit source package paths `scripts/sdd_lifecycle.py` (`mark_ready`,
  `record_pr`, lifecycle classifier and ship-validation CLI), `skills/review/SKILL.md`,
  `skills/ship/SKILL.md`, and their lifecycle test suite (implementation target,
  not AgentsLabs application code). The ship skill delegates the executable
  ancestry/classification/push gate to `scripts/sdd_lifecycle.py`.
