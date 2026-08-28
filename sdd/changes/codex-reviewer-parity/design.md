# Design: codex-reviewer-parity

## Context

The toolkit currently has three mandatory reviewer definitions in `agents/` and
describes panel dispatch in `skills/run/SKILL.md` and `skills/review/SKILL.md`.
Those skills launch Claude `Agent` calls, discover additive project reviewers
from `.claude/agents/sdd-review-*.md`, and require the calls to be parallel.
The Codex adapter currently exposes the shared `skills/` directory through
`.codex-plugin/plugin.json`, but `docs/codex.md` explicitly marks reviewer
panels as unsupported; it has no Codex-specific agent installation surface.

Lifecycle truth already belongs to `STATE.md` and
`scripts/sdd_lifecycle.py`. In particular, the affected
`sdd/specs/ship-and-review-contract.md` owns the `PR_OPEN` review range,
`mark-recertified`, push guard, and `validate-ship` sequence. The smallest
compatible change therefore adds a shared logical panel contract and runtime
dispatch/validation around the existing phase skills, without introducing a
provider framework or a new lifecycle state.

## Decisions

### D1 — One packaged logical reviewer registry

**Chosen:** Add a plugin-owned registry under `skills/reviewer-panel/reviewers/` with one
definition per core role (`sdd-architect`, `sdd-security`, `sdd-qa`). Each
definition contains the stable name, lens, read-only contract, criteria and
referent inputs; applicability metadata is represented with the same
`phases`/`applies_to` fields and matching semantics already used by steering
documents. Treat project `.claude/agents/sdd-review-*.md` files as discovered
project definitions that are normalized into the same logical shape at
dispatch time.

The registry is the source used to derive both runtime prompts and the
expected test plan. It avoids making either Claude agent markdown or Codex
prompt text a second methodology source, while preserving the project-owned
legacy files required by R1/R4.

The registry loader has a fixed mandatory-core invariant: it must contain
exactly one valid definition for each of `sdd-architect`, `sdd-security`, and
`sdd-qa`, and no dispatch or certification may proceed if that invariant is
false. This is a lifecycle invariant, not a second provider-specific list.

Rejected: make `agents/*.md` the cross-runtime source — those files contain
Claude-specific frontmatter/tool declarations and are already runtime-shaped.

Rejected: create a generic provider/plugin framework — it is explicitly out of
scope and would add abstractions without another supported runtime.

### D2 — Claude files remain compatibility adapters

**Chosen:** Keep `agents/sdd-architect.md`, `agents/sdd-security.md`, and
`agents/sdd-qa.md` at their current paths and names. Update them only as
mechanically derived Claude adapters or add a deterministic validator that
compares their stable names, lens/contract markers and criteria references to
the registry. Claude continues to launch these agent types. Legacy project
reviewers remain discovered by filename and their `name` frontmatter, then
normalized before invocation.

This preserves existing Claude installations and MiniMax-through-Claude,
which uses the same Claude path, while detecting missing, duplicate, renamed
or divergent representations before a panel can pass.

Rejected: remove or migrate project `.claude/agents` reviewers immediately —
that breaks the documented additive project extension and violates R3/R4.

### D3 — Codex uses harness-level native subagent orchestration (formal correction, 2026-08-28)

**Formal correction:** The executable plugin runtime does not receive the
native `spawn_agent`/`wait_agent` tool surface. The supported Codex equivalent
to Claude is therefore harness-level orchestration:

```text
deterministic planner -> expected ReviewerPlan
                         |
             Claude harness / Codex harness
               Agent calls / native children
                         |
                 collected raw results
                         v
             deterministic validator -> PanelResult
                         v
              mechanical lifecycle gate
```

The top-level harness, not plugin Python or shell, performs parallel native
spawn, trusted handle-to-role association, wait, and raw collection. The
harness has no certification authority. Plugin code produces the expected
plan and validates the handoff; missing, malformed, unavailable, duplicate,
or out-of-scope results fail closed. The lifecycle gate alone may consume a
validated `PanelResult` before annotation or certification. App Server is not
required, and no user-authored reviewer configuration or agent resource is
introduced. The existing installer's managed `CLAUDE_PLUGIN_ROOT` bridge is
an operational shell-environment setup, not reviewer configuration.

Any earlier direct-executable-dispatch wording is superseded and
non-normative; the runtime adapter boundary is the harness handoff defined
here.

#### Corrected handoff contract

- **Planner output:** ordered expected role IDs, reviewer resource/prompt
  inputs, exact scope and scope ID, applicability decision/reason, source, and
  mandatory/required status.
- **Harness responsibility:** spawn each expected runnable reviewer in one
  native parallel batch, bind each handle to the expected role, wait for every
  handle, and return raw results tagged with the trusted binding. The harness
  must not authorize lifecycle transitions or replace missing results with
  narrative PASS text.
- **Validator input/output:** receive the expected plan and collected raw
  results; normalize identity, scope, status, findings, evidence and
  completeness; return the in-memory `PanelResult` with derived PASS/FAIL.
- **Lifecycle gate:** require that validated PASS result from the same
  invocation. Missing, invalid, unavailable or incomplete results prevent
  section annotation and all certification commands.

#### Runtime evidence

On 2026-08-28, the installed 0.40.0 skill was exercised from the top-level
Codex thread. A deterministic command produced the fixed plan containing
`sdd-architect`, `sdd-security`, and `sdd-qa`. The top-level harness spawned
all three native children in parallel, waited for and collected each assigned
role, and each child remained read-only. Feeding the collected fixed-schema
results to `scripts/reviewer_panel.py` returned exit 0/PASS; removing one
result returned exit 1/FAIL. A plugin child attempting to spawn further native
children was unavailable, confirming that plugin code cannot own the native
tool surface. This experiment is evidence for the corrected boundary, not a
certification of the implementation or lifecycle.

**Corrected choice:** `skills/reviewer-panel/SKILL.md` exposes the planner
output and the exact native handoff instructions to the top-level Codex
harness. It does not call native tools from Python or shell. The harness
performs the parallel child calls, trusted handle binding, waits and raw
collection; the deterministic validator then returns the `PanelResult`.

The installed plugin contains the registry, prompt resources and validator.
The existing adapter installer may automatically write the managed
`CLAUDE_PLUGIN_ROOT` shell-environment bridge in `~/.codex/config.toml`, but
users do not author reviewer definitions, agent files, symlinks, or manual
per-project Codex configuration. This operational bridge is not a reviewer
execution API and does not grant certification authority.

Rejected: install or require custom resources in `~/.codex/agents`, copied
prompts, symlinks, or project Codex reviewer configuration.

Rejected: use App Server or a nested Codex CLI as an orchestration service;
normal plugin use through the top-level harness is the supported product path.

### D4 — Normalize the panel before runtime invocation

**Chosen:** Introduce a logical planning step before any Claude or Codex
invocation. It builds an ordered plan with unique stable reviewer identities,
source (`core` or `project`), lens, applicable decision, and dispatch status.
Core reviewers are unconditional whenever the current lifecycle path requires
a panel. Project reviewers are discovered, parsed, safety-checked and
normalized additively. A malformed, duplicate, unsafe or unresolved project
definition becomes an unavailable plan item and never suppresses a core or
other project reviewer.

The plan is the sole input to runtime dispatch and is also retained in the
panel result for identity and applicability accounting. This makes coverage
runtime-independent and allows parity tests to compare plans before spawning.

Rejected: let each runtime discover and filter reviewers independently — that
is the source of the current Claude/Codex coverage drift.

### D5 — Reuse existing applicability semantics, fail safe

**Chosen:** Add one small deterministic matcher to the shared reviewer
selection implementation in `skills/reviewer-panel/reviewer_plan.py`, using the repository’s existing frontmatter
`phases` and `applies_to` contract and the same phase/mode/scope inputs used to
load steering documents. Valid metadata that definitively excludes the
current phase or scope produces NO MATCH. Missing, ambiguous, malformed,
unsupported, or unevaluable metadata produces UNKNOWN. MATCH produces `run`;
UNKNOWN produces `run`; only definitive NO MATCH may produce a recorded
`skipped` plan item. Core reviewers never pass through this filter.

The dispatch result records the applicability decision and reason for every
project reviewer, including skipped items. An unsafe, malformed, duplicate,
unresolved, or otherwise unavailable definition is not a skip: it is an
unavailable required plan item and forces panel FAIL. There is no second
matching language or new project configuration format.

Rejected: treat missing metadata as non-applicable — it would turn incomplete
project configuration into an assurance reduction.

### D6 — Minimal structured result and closed-world acceptance

**Chosen:** Require exactly one result per planned reviewer that is run. The
transport payload has required non-empty `reviewer_id`, `scope_id`, and
`verdict` (`PASS` or `FAIL`), list-valued `findings` and `evidence`, and
`status` (`complete` or `unavailable`). A `FAIL` includes a finding; a `PASS`
includes the requested scope binding and may have empty findings. Evidence
identifies a repository path or an existing requirement/design/task referent
within the requested scope. The normalized result carries these fields plus
the planned lens and collection status. The collector verifies identity and
scope against the plan, rejects duplicates, spoofed/unknown identities,
malformed or incomplete payloads, and rejects missing or unverifiable
evidence. Missing, unavailable, timeout, interruption, identity mismatch,
out-of-scope output, or any other collection failure is an explicit
non-passing result.

Panel PASS is possible only when the mandatory-core invariant holds, every
mandatory/applicable planned reviewer has one valid collected PASS, every
unavailable item is explicit non-passing, and every skipped item is a
definitive NO MATCH. The lifecycle gate consumes the in-memory panel result at
the same call site that would annotate a section or invoke
`mark-local-verified`/`mark-recertified`; no certification command may run
without a validated PASS result for that invocation. No result normalizer
writes `STATE.md`; lifecycle skills alone perform the existing certification
sequence after PASS. This preserves schema-1 state, section PASS annotations,
and the existing fail-closed security rule.

Rejected: accept free-form prose or infer PASS from a completed process — it
cannot distinguish an unavailable reviewer from an approving reviewer.

### D7 — Preserve exact lifecycle dispatch coverage

**Chosen:** Apply the same logical plan to every supported panel entry point:

- `/sdd:run`: at each completed production-code section, unless `solo`, run
  the selected plan in parallel and wait before accepting the section; retain
  the existing two-fix-round limit and section `panel: PASS` annotation.
- `/sdd:review`: run at feature scale, honoring existing incremental section
  annotations for re-audit scope while always checking cumulative R# coverage
  and cross-section interactions. For `ACTIVE`/`LOCAL_VERIFIED`, PASS keeps
  the standard `mark-local-verified`, `mark-ready --base`, `validate-ship`
  sequence. For `PR_OPEN`, review is exactly `implementation_sha..HEAD`,
  requires the user-pushed HEAD, and PASS calls `mark-recertified` then
  `validate-ship`; it never pushes.
- `/sdd:auto`: panel execution is mandatory (no `solo` substitute), with the
  same plan and result gate in its inline or fresh delegated run/review
  pipeline. Default auto runs the core plus applicable project plan after the
  production run; delegated review uses the same plan for change/drift scope,
  including anchored `PR_OPEN` review. The handoff carries the plan/result
  contract and rejects missing or non-passing results. `PR_OPEN` with an
  unanchored HEAD delegates to `/sdd:review`; auto never calls
  `mark-recertified` itself. Auto still stops before archive.

The `solo` run remains an explicit panel bypass: it invokes no reviewers and
cannot record `panel: PASS`; the default run test proves the opposite.
Existing Claude degraded-panel prose is changed for supported panel paths:
unavailable core or applicable project reviewers block panel PASS and the
associated lifecycle advancement. No inline substitution silently satisfies
a missing mandatory reviewer.

This confines the change to reviewer selection/dispatch/result validation and
cross-references the existing state-dependent contract instead of duplicating
or altering lifecycle transitions.

Rejected: add a separate Codex-only auto or PR certification flow — it would
create the second methodology the proposal excludes and could diverge from
`ship-and-review-contract.md`.

#### D7 runtime-boundary correction

For all three lifecycle paths, the skill is the orchestration instruction to
the current top-level harness. The harness performs the reviewer calls and
returns the handoff; the deterministic validator is invoked with that handoff
before any section annotation or certification command. `run` solo remains an
explicit no-panel bypass. `review` certification and recertification retain
their existing state/range rules but require validated PASS evidence from the
same invocation. `auto` may delegate through the same harness contract but
cannot invent reviewer completion or call recertification independently.

### D8 — Package and validate both runtime representations together

**Chosen:** Ship the logical registry, Codex adapter instructions/resources,
Claude compatibility adapters, and deterministic validators in the plugin
repository. Update `.claude-plugin/plugin.json` and
`.codex-plugin/plugin.json` together when distributed behavior changes, keep
their versions aligned, and validate that every registry reviewer has exactly
one valid Claude representation plus a Codex-dispatch representation. Extend
packaging checks to assert the installed Codex tree contains all adapter
resources and never depends on consumer `.claude/agents` or user-local
`~/.codex/agents`.

Project reviewers remain project-owned and are not copied into the plugin.
The existing Codex install-root mechanism continues to provide
`CLAUDE_PLUGIN_ROOT`; no new global configuration is needed.

Rejected: package project reviewers or toolkit tests into consumer projects —
the repository boundary and current validator explicitly prohibit that.

### D9 — Derive parity and smoke coverage from the registry

**Chosen:** Add standard-library deterministic tests under `tests/` that load
the registry, assert the fixed mandatory-core invariant, and derive expected
plans for equivalent `run` (default and `solo`), `review` change/drift, and
each applicable `auto` state. Compare provider plans, then capture Claude
invocation requests and Codex spawn/wait/collection requests separately so the
oracle is not circular: exact IDs, counts, parallel batch boundaries, waits,
and rejection of extras are observable adapter assertions. Fixtures cover
project MATCH/UNKNOWN/NO MATCH, malformed/duplicate/unsafe definitions,
legacy `.claude/agents` compatibility, and all result failure classes.
Assertions prove no lifecycle advancement or approval evidence on failure and
preserve read-only reviewer policy.

The test plan includes an R1–R6 traceability table, named behavioral modules
and fixtures, package-tree checks for every registry/adapter resource, default
versus solo behavior, review change/drift scopes, and auto inline/delegated,
project-reviewer, and `PR_OPEN` paths. The opt-in native Codex smoke test
verifies actual spawn, parallelism, wait, identity, collection, sandbox, and
unchanged worktree; paid model execution is never a CI requirement.

Add an opt-in native Codex smoke test that is skipped unless explicitly
enabled/configured. It verifies parallel spawn, wait, role identity, result
collection, and no repository mutation; paid model execution is never a CI
requirement. Packaging tests validate both manifests and all packaged
resources.

Rejected: hard-code a second expected reviewer list in tests — derived tests
would then reproduce the drift they are intended to detect.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Logical reviewer contract | `skills/reviewer-panel/reviewers/` and `skills/reviewer-panel/reviewer_plan.py` | Canonical identities, criteria, read-only contract, applicability metadata, and in-memory plan/result contracts. |
| Claude adapter | `agents/sdd-architect.md`, `agents/sdd-security.md`, `agents/sdd-qa.md` | Preserve names/paths; mechanically align or validate them against the registry. |
| Dispatch | `skills/run/SKILL.md`, `skills/review/SKILL.md`, `skills/auto/SKILL.md` | Select/normalize once, dispatch the same plan through Claude or native Codex, collect the minimal result, and fail closed. |
| Codex distribution | `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `docs/codex.md` | Package/discover adapter resources, document native panel support and Claude/MiniMax compatibility, and keep manifest/version checks aligned. |
| Validation and tests | `scripts/validate_toolkit.py`, `tests/` and explicit fixtures | Mechanical representation/parity/packaging checks and opt-in native smoke coverage. |
| Lifecycle contract | `sdd/specs/ship-and-review-contract.md` (cross-reference only) | Preserve the existing state/range/recertification semantics; no new state or schema. |

The future archive step creates `sdd/specs/reviewer-parity.md` as the living
specification named by the proposal. This design does not create or update
that spec during the design phase.

## Requirement traceability

| Proposal requirement | Design decision | Verification boundary |
|---|---|---|
| R1 Runtime-independent reviewer selection | D1, D4, D7 | Captured Claude/Codex requests and identical logical plans, including mandatory core and legacy project reviewers |
| R2 One logical source and thin adapters | D1, D2, D4, D8 | Registry-to-adapter drift validator and provider plan equality |
| R3 Native Codex execution and plugin distribution | D3, D8 | Captured native spawn/wait/collection requests, sandbox smoke test, and installed package-tree test |
| R4 Fail-safe project-reviewer applicability | D4, D5 | Deterministic MATCH/UNKNOWN/NO MATCH and safe-path fixtures |
| R5 Structured fail-closed results and lifecycle parity | D6, D7 | Result failure matrix and lifecycle non-advancement/certification-gate tests |
| R6 Mechanical parity and regression coverage | D8, D9 | Derived provider parity, packaging, compatibility, and opt-in native smoke tests |

The test harness uses a fake Claude launcher and fake native Codex spawn
surface for deterministic assertions. They record requests and return fixed
valid/invalid payloads; neither requires a paid model. The real native smoke
test is opt-in and is the only test that depends on the installed Codex
runtime.

## Data & interfaces

The new internal interfaces are intentionally small and in-memory:

- `ReviewerDefinition`: stable name, source/lens, criteria, read-only
  contract, and optional `phases`/`applies_to` metadata.
- `ReviewerPlan`: normalized reviewer identity, applicability decision,
  dispatch state, and exact review scope.
- `ReviewerResult`: plan identity, verdict, findings, evidence/referents, and
  collection status.
- `PanelResult`: plan/results, skipped applicability decisions, and a derived
  PASS/FAIL gate decision.

These are dispatch contracts, not persisted lifecycle schemas. Only the
existing lifecycle commands may write certification fields in `STATE.md`.
No telemetry platform, event graph, token ledger, context hash, new event ID,
or lifecycle state is introduced.

## Risks & mitigations

- **Codex native API variation:** keep the adapter behind the shared dispatch
  contract and make the smoke path opt-in; inability to spawn/wait/collect is
  visible FAIL, never a certification PASS.
- **Prompt drift:** generate runtime prompts from the registry and compare
  runtime representations mechanically in validation.
- **Legacy project reviewer ambiguity:** preserve filename discovery, normalize
  only valid definitions, run UNKNOWN, and record malformed/unavailable items
  without suppressing other reviewers. Require a repository-local regular file,
  safe resolved path, filename/name consistency, and only documented
  frontmatter fields. The canonical generated prompt/read-only contract has
  precedence over reviewer-body directives. Unsafe or ambiguous definitions
  are unavailable and non-passing, never skipped.
- **Parallel collection races or duplicate output:** key collection by the
  planned identity and reject duplicates, unknown IDs, and incomplete sets.
- **Assurance regressions from optimization:** applicability can skip only
  definitive NO MATCH; token reduction is limited to shared referents and
  incremental review scope already defined by the existing skills.
- **Lifecycle drift:** leave `sdd_lifecycle.py`, STATE schema-1, and the
  `PR_OPEN` contract unchanged except for the panel gate's call site. The gate
  must receive the validated in-memory PASS capability from that same panel
  invocation before it can annotate a section or certify lifecycle state.

## Open questions

None. The proposal’s remaining choices are resolved by repository evidence:
the existing skills are the shared lifecycle surface, the manifests are the
packaging surface, the current `agents/` files are Claude-shaped compatibility
resources, and native Codex spawn is the only requested runtime capability
that does not require a new user-local resource model.
