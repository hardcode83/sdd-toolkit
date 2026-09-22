# Design: Runtime / provider / model agnostic foundation

## Context

The audit of 2026-09-22 confirmed: no model IDs anywhere in executable surfaces
(enforced by `tests/test_decisions_contract.py:75-82`); a single process-spawn
point (`scripts/sdd_auto_outcome.py:137-182`); full environment inheritance in
`delegated_environment` (line 214-224); and a model-agnostic SDD core
(`reviewer_panel.py`, `reviewer_plan.py`, `sdd_lifecycle.py`, `sdd_session.py` —
Python + git + disk only). The Codex runtime support already exists as an
experimental adapter (`.codex-plugin/plugin.json` pointing at the shared
`skills/`, `scripts/codex-adapter-install.sh` supplying
`${CLAUDE_PLUGIN_ROOT}` via `shell_environment_policy.set`, a native panel
handoff in `reviewer_plan.py:404-500`, and `tests/test_codex_smoke.py`). The
architecture steering (`sdd/steering/architecture.md:8-10`) already states the
conceptual split this change makes explicit: "Runtime adapters translate shared
lifecycle decisions into Claude or Codex execution primitives."

## Decisions

### D1 — Three layers, with configuration acquisition as a runtime responsibility

**Chosen:** the capability model is defined as three layers — SDD core
(lifecycle, reviewer plan/gates, receipts, identity binding, Git/worktree
safety, resume; everything in `scripts/sdd_lifecycle.py`,
`scripts/reviewer_panel.py`, `skills/reviewer-panel/reviewer_plan.py`,
`scripts/sdd_session.py`), runtime adapter (how work executes: Claude Code
skills/forks/`Agent`/`claude -p`; Codex CLI skills/native panel handoff), and
provider/model capability (what a backend can do). The SDD core consumes a
capability profile through the runtime adapter and never knows the concrete
configuration source. For the Claude Code adapter, this change implements the
profile env-derived; for Codex CLI no profile source is implemented or imposed.

Rejected: a universal configuration framework with pluggable sources — only one
real source exists today (Claude Code env); the two-implementations rule
forbids the abstraction.

Rejected: env as the universal source for all runtimes — Codex configuration
lives in Codex's own config surface; nothing in this change forces
`ANTHROPIC_*` on it.

### D2 — The env-derived profile is one small stdlib module with honest `unknown`s

**Chosen:** a new `scripts/provider_profile.py` (stdlib only) exposing
`read_claude_code_profile(env) -> dict` with fields: `base_url`,
`alias_map` (only the aliases whose `ANTHROPIC_DEFAULT_<ALIAS>_MODEL` is set),
`structured_output`, `effort`, `budget_semantics`, `fallback` — the last four
default to `"unknown"` unless determinable from env, never guessed. No runtime
auto-detection: the module documents that it implements the Claude Code source
only; another runtime's change implements its own source behind the same
conceptual interface.

Rejected: detecting the runtime from environment heuristics — fragile, and
this change has no second runtime that needs it.

### D3 — One shared alias preflight, hard stop, called before any panel/implementer launch

**Chosen:** the alias-mapping check moves from its private home in
`sdd_auto_outcome.py` (`provider_warnings`, lines 193-211) into
`provider_profile.py` as `alias_warnings(aliases, env)` plus a CLI
(`python3 scripts/provider_profile.py check --aliases sonnet,opus`), which
`sdd_auto_outcome.py` reuses (keeping its public function and behavior for
existing callers/tests). The `run`, `review`, and `auto` skills gain one step:
before the first `Agent` launch, run the preflight for the aliases the phase
will use (`sonnet`, `opus`); on missing mappings, stop the phase and report the
exact variable names (exit 1). This is loud and fail-closed, matching the
proposal; it degrades nothing when `ANTHROPIC_BASE_URL` is unset (native
Anthropic: no check needed) and passes full model names through untouched.

Rejected: warning-only — a panel that will certainly die on its first request
is exactly the silent-in-practice failure the preflight exists to remove.

Rejected: a doctor check instead of a phase step — doctor is a periodic audit;
this must fire at the moment of launch. (Doctor integration remains a possible
follow-up, not this change.)

### D4 — Reviewer dispatch regression as a dedicated test module with two executable arms

**Chosen:** a new `tests/test_reviewer_dispatch_regression.py` pins the
incident pattern at the level where it happened — dispatch/orchestration, not
just payload validation:
- **Correct arm:** a fake launcher delivers one caller-bound envelope per
  planned reviewer (`invocation_id`, `planned_reviewer_id` = the launched
  identity, `payload`) to `dispatch_claude_panel`; the panel PASSes; a gate
  invocation (`reviewer_panel.py --phase review ... --results`) writes a
  receipt; `sdd_lifecycle.ensure_panel_receipt` accepts it for certification.
- **Failure arm:** the historical pattern is simulated — reviewer output
  arrives outside the caller-bound collection (envelopes missing trusted
  identity / results count short / verdict claimed with no gate run). Each
  variant must produce: gate FAIL or refusal, **no certification** (no receipt
  → `ensure_panel_receipt` raises → `mark-local-verified` unreachable), and the
  claimed PASS treated as not having happened.
Existing gate tests (`test_panel_contract.py`, `test_reviewer_results.py`,
`test_reviewer_adapters.py`) cover payload validation; this module covers the
orchestration path end to end at the Python boundary.

Rejected: testing only `normalize_reviewer_result` rejections — that is the
already-pinned contract; the incident was an orchestration/scheduling failure.

### D5 — Recipes split by runtime group; Codex documented from evidence, not analogy

**Chosen:** `references/models.md` keeps the Anthropic-compatible group (Claude
Code runtime × Anthropic/Kimi/MiniMax providers): exact env recipes per
provider, alias mapping, and a new quota-semantics section (`--max-budget-usd`
does not protect usage-window quotas; observed Auto Mode classifier behavior on
non-Anthropic gateways, documented without optimization prescription).
`docs/codex.md` gains a short "Configuration surface" section stating from
evidence what Codex actually consumes: its own session model configuration and
the `shell_environment_policy.set` block from `codex-adapter-install.sh`;
explicitly stating that tier aliases and `ANTHROPIC_*` variables are not Codex
configuration (the frontmatter aliases document intent only, per the existing
known-limitations entry).

Rejected: one recipe section covering all four backends — that is precisely
the forced analogy the proposal forbids.

### D6 — Codex inventory lives in this design, classified per item

See "Codex support inventory" below (R6). The durable artifact is the
classification table here; `references/runtime-provider.md` (D7) summarizes the
layer model only.

### D7 — The layer model is one reference document

**Chosen:** a new `references/runtime-provider.md` documents the three layers,
classifies each toolkit surface (with file paths) as core / runtime-specific /
provider capability, states the two-implementations rule, and defines the
profile schema and `unknown` semantics. The preflight contract (D3) and the
BLOCKED/INCOMPATIBLE-never-PASS rule for runtimes that cannot guarantee
foreground caller-bound collection are stated there as standing rules.

## Codex support inventory (R6)

| Item | Classification | Evidence |
|---|---|---|
| `.codex-plugin/plugin.json` → shared `skills/` | A. Legitimate runtime dependency | `docs/codex.md:22-24` — no copied methodology |
| `codex-adapter-install.sh` (`CLAUDE_PLUGIN_ROOT` via `shell_environment_policy.set`) | A. Legitimate runtime dependency — runtime-specific config bridge | `docs/codex.md:26-53` |
| Native panel handoff (`build_codex_handoff`, `validate_codex_handoff`, `dispatch_codex_panel`) | A. Legitimate runtime dependency — the runtime adapter boundary already exists | `reviewer_plan.py:404-500`; `tests/test_codex_smoke.py` |
| `review`/`ship`/`archive`/`status`/`history` Claude frontmatter (`context: fork`, `background`, `effort`) ignored by Codex | D. Stays runtime-specific; skills already degrade by design (HANDOFF blocks) | `docs/codex.md:108-115` |
| Tier aliases in skill/agent frontmatter under Codex | D. Intent documentation only; no model selection | `docs/codex.md:122-126` |
| Worktree isolation without `EnterWorktree` (manual `git worktree add` + `claim`) | D. Stays runtime-specific handoff; never silently ignored | `docs/codex.md:94-95` |
| `sdd_auto_outcome.py` headless delegation under Codex (`claude -p` spawn) | C. Capability to abstract — **out of this change**; documented fallback is inline execution (`AUTO_OUTCOME: UNAVAILABLE`) | `docs/codex.md:92` |
| Telemetry (`usage-*.sh`, OTel sink) | D. Stays Claude-runtime-specific | `docs/codex.md:97` |
| `AskUserQuestion` absence under Codex | D. Stays runtime-specific; HANDOFF is the shared contract | `docs/codex.md:134-136` |
| Tournament orchestration (Claude Agent + worktrees) | D. Unsupported under Codex, documented | `docs/codex.md:96` |

No item was found that is an accidental coupling (B) in the sense of "works by
luck and should not"; the existing adapter boundaries are deliberate.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Capability profile + preflight (new) | `scripts/provider_profile.py` | `read_claude_code_profile(env)`, `alias_warnings(aliases, env)`, CLI `check --aliases` |
| Headless recipe | `scripts/sdd_auto_outcome.py` | `provider_warnings` re-implemented on the shared check; public behavior preserved |
| Phase skills | `skills/run/SKILL.md`, `skills/review/SKILL.md`, `skills/auto/SKILL.md` | One preflight step before the first `Agent` launch (aliases `sonnet,opus`); hard stop with exact missing variables |
| Env inheritance regression (R3) | `tests/test_sdd_auto_outcome.py` | Fake executable records full env; asserts `ANTHROPIC_BASE_URL`, credential vars, `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_*_MODEL` propagate and only the two SDD guards are added |
| Profile tests | `tests/test_provider_profile.py` (new) | Profile fields and `unknown` semantics; alias check positive/negative/passthrough; CLI exit codes |
| Dispatch regression (R4) | `tests/test_reviewer_dispatch_regression.py` (new) | Two-arm dispatch/orchestration regression per D4 |
| Recipes (R5) | `references/models.md` | Kimi recipe; quota-semantics section; group restructure |
| Layer model (R1) | `references/runtime-provider.md` (new) | Three layers, surface classification, two-implementations rule, profile schema, BLOCKED/INCOMPATIBLE rule |
| Codex docs (R5) | `docs/codex.md` | "Configuration surface" section per D5 |
| Release | `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` | Version bump together (repo rule; `validate_toolkit.py` enforces parity) |

## Data & interfaces

`provider_profile.py`:

```python
def read_claude_code_profile(env: Mapping[str, str] | None = None) -> dict:
    # {"base_url": str|None, "alias_map": {alias: model},
    #  "structured_output": "unknown", "effort": "unknown",
    #  "budget_semantics": "unknown", "fallback": "unknown"}

def alias_warnings(aliases: Iterable[str], env: Mapping[str, str] | None = None) -> list[str]:
    # one actionable message per unmapped alias when ANTHROPIC_BASE_URL is set

# CLI: python3 scripts/provider_profile.py check --aliases sonnet,opus
# exit 0 = no warnings; exit 1 = missing mappings printed to stderr
```

No changes to `reviewer_panel.py`, `reviewer_plan.py`, `sdd_lifecycle.py`,
`reviewer-panel` SKILL contract, receipts schema, or lifecycle transitions. The
profile/preflight never writes state; it reads env and reports.

## Risks & mitigations

- **Skill text edits break contract tests.** `validate_toolkit.py` and
  `test_decisions_contract.py` scan skill text (aliases only, no model IDs —
  the preflight step mentions aliases, which is allowed). Mitigation: run the
  full suite + `validate_toolkit.py all` before the section panel.
- **`provider_warnings` behavior drift.** Existing tests pin its signature and
  messages; the shared implementation must keep both. Mitigation: keep the
  function as a thin wrapper; run existing tests unchanged.
- **Preflight false positives.** A user with a gateway that transparently
  serves Anthropic model IDs would be stopped unnecessarily. Mitigation: the
  check only fires when `ANTHROPIC_BASE_URL` is set and only reports; a full
  model name is always passed through (R2 criterion 3), and the skill step says
  to stop only on exit 1 with the reported variables — a deliberate, visible
  decision point, not a silent block.
- **Docs rot.** Recipes for Kimi/MiniMax depend on provider behavior outside
  this repo. Mitigation: each recipe states the observed date and the
  observable verification command.

## Open questions

None. Every decision above is covered by the approved proposal (R1–R6). The
BLOCKED/INCOMPATIBLE classification for runtimes that cannot guarantee
foreground caller-bound collection (R4 criterion 3) is stated as a standing
rule in `references/runtime-provider.md`; its runtime-level proof belongs to
the conformance suite, which is explicitly out of scope.
