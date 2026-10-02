# Proposal: Runtime / provider / model agnostic foundation

## Why

The toolkit already runs its SDD core (lifecycle, reviewer plan and gates,
receipts, identity binding, Git/worktree safety) on plain Python and disk, and
its skills speak in model tiers rather than model IDs. The audit of 2026-09-22
confirmed there are no hardcoded model IDs and no fixed context-window
constants, and that the only process spawn is the headless recipe in
`scripts/sdd_auto_outcome.py`. What does not exist yet is an explicit,
testable statement of which parts of the toolkit are SDD core, which are
runtime (Claude Code today, Codex CLI documented), and which are provider/model
capabilities (Anthropic, Kimi, MiniMax, OpenAI) — plus the guards that turn an
incomplete provider configuration (the classic: `ANTHROPIC_BASE_URL` set with
only `ANTHROPIC_MODEL`, so every `Agent` alias launch fails on the first
request) into a loud, actionable preflight instead of a dead panel. This
change establishes that foundation so later changes can add adapters and
optimizations without touching the SDD core contract.

## What changes

After this change: (1) a documented and minimally machine-readable capability
model separates SDD core from runtime adapter from provider/model, with
configuration and capability acquisition defined as runtime-specific — the SDD
core never knows the concrete source — and an env-derived capability profile
implemented for the Claude Code adapter; (2) a provider
preflight detects incomplete alias mappings and warns with an actionable
message before any phase launches reviewers or implementers; (3) regression
tests pin environment inheritance for delegated sessions and the reviewer
foreground/caller-bound-identity contract, including the historical
background-reviewer failure as an executable failure case; (4) provider
recipes for Kimi, MiniMax, and Codex/OpenAI document the exact environment
each backend needs, its quota/budget semantics, and what stays runtime-specific
vs what is provider capability. No gate, receipt, lifecycle rule, or reviewer
contract changes.

## Requirements

### R1 — Explicit capability model with runtime-specific configuration sources

**As a** toolkit maintainer, **I want** the separation of SDD core, runtime
adapter, and provider/model capability to be explicit, with capability and
configuration acquisition defined as a runtime responsibility, **so that**
later changes can add or adjust runtimes and providers without re-litigating
what is contract and what is implementation detail, and without the SDD core
ever depending on one configuration source.

Acceptance criteria:

1. WHEN the change is archived, THE SYSTEM SHALL provide a reference document
   that classifies each toolkit surface (skills, agents, scripts, flags,
   telemetry) as SDD core, runtime-specific, or provider capability, and SHALL
   state the rule that an abstraction requires at least two real
   implementations.
2. WHEN the capability model is defined, THE SYSTEM SHALL state that obtaining
   configuration and capabilities is runtime-specific: the SDD core consumes a
   capability profile through the runtime adapter and SHALL NOT know or assume
   the concrete source (environment variables, runtime config files, or any
   other mechanism the runtime uses).
3. WHEN the Claude Code adapter needs a capability profile, THIS CHANGE SHALL
   implement it env-derived for Claude Code with Anthropic-compatible gateways
   (reading `ANTHROPIC_BASE_URL`, the `ANTHROPIC_DEFAULT_<ALIAS>_MODEL`
   family, and related variables), exposing at minimum: alias-to-model mapping,
   structured-output support, effort support, budget semantics, and fallback
   support, each with an `unknown` state when not determinable.
4. IF a capability cannot be determined from the runtime's configuration,
   THEN THE SYSTEM SHALL record it as `unknown` and SHALL NOT guess a
   provider-specific value.
5. WHEN a runtime without an implemented profile source is in use (e.g. Codex
   CLI), THE SYSTEM SHALL NOT impose `ANTHROPIC_*` variables or tier aliases on
   it; the profile source for that runtime is defined by its own change.

### R2 — Provider preflight

**As a** user running any phase behind a non-Anthropic gateway, **I want** the
toolkit to check that the model aliases the phase will launch are mapped
before any reviewer or implementer is spawned, **so that** the failure is a
loud, actionable configuration error instead of a panel that dies on its first
request.

Acceptance criteria:

1. WHEN `ANTHROPIC_BASE_URL` is set and a phase would launch `Agent` calls
   with aliases `haiku`, `sonnet`, or `opus`, THE SYSTEM SHALL verify the
   corresponding `ANTHROPIC_DEFAULT_<ALIAS>_MODEL` variables are set and SHALL
   report every missing mapping with the exact variable name before launching.
2. WHEN the session model of a delegated run is checked, THE SYSTEM SHALL use
   the same preflight as the `Agent` launches (one shared check, not two
   divergent ones).
3. IF a full model name is passed instead of an alias, THEN THE SYSTEM SHALL
   pass it through without requiring any alias mapping.

### R3 — Environment inheritance regression

**As a** maintainer, **I want** a test that proves a delegated session receives
the provider environment of its parent, **so that** no future refactor of the
headless recipe can silently reroute a child to a different backend.

Acceptance criteria:

1. WHEN `sdd_auto_outcome.py run` launches the delegated executable, THE
   SYSTEM SHALL propagate `ANTHROPIC_BASE_URL`, the API credential variables
   (`ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`), `ANTHROPIC_MODEL`, and the
   `ANTHROPIC_DEFAULT_<ALIAS>_MODEL` variables, demonstrated by a test with a
   fake executable that records its environment.
2. WHEN a delegated session inherits the environment, THE SYSTEM SHALL add
   only the `SDD_AUTO_DELEGATED` and `SDD_AUTO` guards on top of the parent
   environment, demonstrated by the same test.

### R4 — Reviewer identity and foreground dispatch regression

**As a** maintainer, **I want** an executable regression over the reviewer
dispatch/orchestration path that proves results only certify when they arrive
caller-bound in the foreground, **so that** the historical incident — reviewers
launched in background from a fork; the fork ended its turn; the results
returned to the parent; reviewers showed PASS with no receipt and
`STATE.local_review` stuck at PENDING — can never regress silently.

Acceptance criteria:

1. WHEN reviewer results are validated, THE SYSTEM SHALL require one envelope
   per planned reviewer carrying `invocation_id`, `planned_reviewer_id`, and
   `payload`, with `planned_reviewer_id` as the only trusted identity, and
   SHALL fail closed on duplicates, swaps, or self-declared identity — this is
   the existing gate contract, pinned by a regression test demonstrating that a
   swapped or missing trusted binding is rejected.
2. WHEN the dispatch/orchestration path is exercised in a test, THE SYSTEM
   SHALL demonstrate both arms of the incident pattern: the correct path
   (reviewers launched foreground, in the same caller turn, envelopes
   caller-bound, gate run, receipt emitted by `reviewer_panel.py`, lifecycle
   certification accepted) and the failure path (reviewer work returned outside
   the caller-bound collection — e.g. results arriving after the collecting
   turn ended, or a panel verdict claimed without a receipt on disk), and SHALL
   prove the failure arm cannot produce certification: no receipt, no
   `mark-local-verified` acceptance, panel verdict treated as not having
   happened.
3. IF a runtime or harness cannot guarantee foreground, same-turn, caller-bound
   collection of every planned reviewer, THEN THE SYSTEM SHALL classify that
   runtime/harness as BLOCKED/INCOMPATIBLE for panel certification and SHALL
   NEVER convert such a condition into a PASS.

### R5 — Provider recipes and quota semantics

**As a** user on Kimi, MiniMax, or Codex/OpenAI, **I want** the toolkit
documentation to state the exact configuration recipe each backend needs and
its quota/budget semantics, **so that** I can configure a backend in one read
and know which toolkit protections are real on it.

Acceptance criteria:

1. WHEN a user reads the models reference, THE SYSTEM SHALL provide a recipe
   for the Anthropic-compatible group — Claude Code as runtime with Anthropic,
   Kimi, or MiniMax as provider — naming the environment variables to set and
   the aliases each tier resolves to through them.
2. WHEN a user runs the Codex CLI runtime with OpenAI models, THE SYSTEM SHALL
   document the real configuration surface of that runtime as evidenced by the
   repository's existing Codex support (adapter manifest, `docs/codex.md`,
   adapter install script, panel handoff), and SHALL NOT document
   `ANTHROPIC_*` variables or tier aliases for Codex unless evidence shows the
   existing adapter actually consumes them.
3. WHEN a backend bills by usage windows rather than per-token USD, THE
   SYSTEM SHALL document that `--max-budget-usd` does not protect that quota,
   and SHALL document the observed Auto Mode classifier behavior on
   non-Anthropic gateways (classifier requests consume provider quota) without
   prescribing an optimization that has no measurement behind it.

### R6 — Codex support inventory

**As a** maintainer, **I want** every existing Codex surface inventoried and
classified as legitimate runtime dependency, accidental coupling, capability to
abstract, or behavior that must stay runtime-specific, **so that** the Codex
adapter is extended deliberately instead of by assumption.

Acceptance criteria:

1. WHEN the design is written, THE SYSTEM SHALL inventory the existing Codex
   support (adapter manifest, `docs/codex.md`, smoke tests, native panel
   handoff in `reviewer_plan.py`, any scripts) and classify each item per the
   four categories above, with evidence.
2. WHEN a difference between Claude Code and Codex is classified, THE SYSTEM
   SHALL cite the concrete file or behavior that demonstrates it.

## Out of scope

- Implementing a `codex exec` headless adapter or any new runtime adapter
  (follow-up change, after this foundation lands).
- Changing the headless recipe flags (`--json-schema`, `--effort`,
  `--max-budget-usd`, `--permission-mode auto`) based on provider capabilities
  (follow-up; needs the conformance measurements).
- Auto Mode classifier cost optimizations (prohibited without measurement;
  tracked as a conformance-suite output, not this change).
- Multi-currency usage metrics (`usage-sync.py` cost labeling) — follow-up.
- Any change to gates, receipts, lifecycle transitions, reviewer mandatory
  core, fix-ladder caps, or the fail-closed panel semantics. Invariant.
- The conformance fixture suite itself (designed here, implemented as its own
  change).

## Affected specs

- `sdd/specs/reviewer-parity.md` — may gain a note pinning the foreground /
  trusted-binding contract at archive time.
- `sdd/specs/runtime-provider-contract.md` *(no existe aún — se creará al
  archivar)* — the capability model and preflight contract.
