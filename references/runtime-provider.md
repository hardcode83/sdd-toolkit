# Runtime / provider / model — the three layers

The toolkit is a plugin distributed to coding runtimes (architecture steering:
"Runtime adapters translate shared lifecycle decisions into Claude or Codex
execution primitives"). This reference is the explicit, testable statement of
which part of the toolkit is which layer, so later changes can add runtimes
and providers without re-litigating what is contract and what is
implementation detail. It summarizes the layer model; the per-item Codex
inventory with evidence lives in the design of the foundation change
(`sdd/changes/runtime-provider-agnostic-foundation/design.md`, "Codex support
inventory").

## The three layers

1. **SDD core** — what a phase must do, independent of how work executes:
   lifecycle transitions, gates, receipts, reviewer plan and result gate,
   identity binding, Git/worktree safety, resume. Pure Python + git + disk;
   no model names, no process spawns except the one headless recipe, no
   knowledge of where configuration comes from.
2. **Runtime adapter** — how work executes in a concrete runtime: skill
   frontmatter semantics, forks and `Agent` launches, the headless recipe,
   panel dispatch, runtime-specific configuration bridges.
3. **Provider/model capability** — what a backend can do: which models an
   alias resolves to, structured-output and effort support, budget and quota
   semantics, fallback behavior.

A change touches exactly one layer wherever possible. A capability that
belongs to layer 3 must never be answered inside layer 1; a layer-2 mechanism
must never be required by layer 1's contract.

## Surface classification

### SDD core

| Surface | Files |
|---|---|
| Lifecycle transitions, queue, gates, receipts, identity binding | `scripts/sdd_lifecycle.py` |
| Panel gate and receipt writer | `scripts/reviewer_panel.py` |
| Shared reviewer plan, planner/result gate, panel dispatch (Claude and Codex entry points) | `skills/reviewer-panel/reviewer_plan.py` |
| Git/worktree session safety (check / policy / claim / resolve / orphans) | `scripts/sdd_session.py` |
| Roadmap graph (frontier, waves, critical path, dependency checks) | `scripts/sdd_roadmap.py` |
| Audit of SDD state consistency | `scripts/sdd-doctor.py` |
| Phase methodology (what each phase must verify before `[x]`) | `skills/*/SKILL.md` text, `rules.md`, `templates/` |

The reviewer-panel resource is self-contained on purpose: the core registry
and the shared logical plan are one file both runtimes consume, so the
methodology has a single home.

### Runtime adapter — Claude Code

| Surface | Files |
|---|---|
| Tier-alias frontmatter and `Agent` calls (`context: fork`, `background`, `effort`, `model: <alias>`) | `skills/*/SKILL.md`, `agents/sdd-architect.md`, `agents/sdd-qa.md`, `agents/sdd-security.md`, `templates/reviewer-template.md` |
| Headless recipe: the single process spawn (`claude -p`, `--permission-mode auto`, `--json-schema`, `--max-budget-usd`, …) | `scripts/sdd_auto_outcome.py` |
| Env-derived capability profile and alias preflight | `scripts/provider_profile.py` |
| Claude telemetry (usage scripts, OTel sink) | `scripts/usage-*.sh`, `scripts/usage-sink.py`, `scripts/usage-sync.py` |

Consumer-project reviewers are a different surface: each SDD project
creates its `sdd-review-*.md` agents at `.claude/agents/sdd-review-*.md`
from the toolkit's `templates/reviewer-template.md`. Those files are
project-local and are not toolkit-shipped; the toolkit ships only the
template and its own panel agents listed above.

### Runtime adapter — Codex CLI (experimental)

| Surface | Files |
|---|---|
| Adapter manifest pointing at the shared skills | `.codex-plugin/plugin.json` |
| `${CLAUDE_PLUGIN_ROOT}` bridge via `shell_environment_policy.set` in `~/.codex/config.toml` | `scripts/codex-adapter-install.sh` |
| Native panel handoff (`build_codex_handoff`, `validate_codex_handoff`, `dispatch_codex_panel`) | `skills/reviewer-panel/reviewer_plan.py`; smoke tests `tests/test_codex_smoke.py` |
| Runtime documentation (installation, invocation, compatibility, limitations) | `docs/codex.md` |

Runtime-specific resources stay adapters or generated artifacts — never
independently maintained methodology copies (architecture steering
anti-patterns). The shared `skills/` directory is consumed by both runtimes;
nothing is forked per runtime.

### Provider/model capability

| Surface | Where it lives |
|---|---|
| Alias-to-model mapping (`ANTHROPIC_DEFAULT_<ALIAS>_MODEL` family), `ANTHROPIC_BASE_URL`, credential variables | The user's Claude Code environment; observed through the profile |
| Provider recipes and quota semantics (MiniMax, Kimi; `--max-budget-usd` vs usage windows; Auto Mode classifier traffic) | `references/models.md` |
| Codex session model configuration | Codex's own configuration surface (`docs/codex.md`, "Configuration surface") |

## Standing rules

### A new abstraction requires two real implementations

An abstraction may enter the SDD core only when at least two real
implementations exist behind it. With one implementation it stays
runtime-specific. This is why there is no universal configuration framework
and no runtime auto-detection in this change: today one env-derived source
exists, so the profile source stays a Claude Code adapter concern until a
second runtime's change implements its own source behind the same conceptual
interface.

### Configuration acquisition is runtime-specific

The SDD core consumes a capability profile through the runtime adapter and
never knows or assumes the concrete source — environment variables, runtime
config files, or any other mechanism the runtime uses. Implemented source
today: env-derived, for the Claude Code runtime only
(`scripts/provider_profile.py`, `read_claude_code_profile`). No source is
implemented or imposed for Codex CLI; the profile source for that runtime is
defined by its own change, and `ANTHROPIC_*` variables and tier aliases are
not Codex configuration (R1).

### Capability profile schema and `unknown` semantics

The profile the runtime adapter hands to the SDD core has this schema
(`scripts/provider_profile.py`):

| field | meaning |
|---|---|
| `base_url` | the gateway endpoint, or `None` when `ANTHROPIC_BASE_URL` is unset |
| `alias_map` | only the aliases whose `ANTHROPIC_DEFAULT_<ALIAS>_MODEL` is set, mapped to the model name they resolve to |
| `structured_output` | whether the backend supports the structured-output flags the recipe uses |
| `effort` | whether the backend supports the effort flag |
| `budget_semantics` | how the backend bills (per-token USD, usage windows, …) |
| `fallback` | whether a fallback model is available |

Rule: **a capability the runtime's configuration does not deterministically
expose is recorded as `unknown` and is never guessed** (the constant is
`provider_profile.UNDETERMINED`). Today the last four fields are always
`unknown` — no env variable determinably signals them — and that honesty is
the contract, not a gap to fill by assuming Anthropic defaults. The profile
never writes state; it reads configuration and reports.

### Preflight contract (D3)

Before a phase on the Claude Code runtime launches its first `Agent`, the
aliases the phase will use — `sonnet` and `opus` — are checked with one shared
implementation:

```bash
python3 scripts/provider_profile.py check --aliases sonnet,opus
```

When `ANTHROPIC_BASE_URL` is set and an alias lacks its
`ANTHROPIC_DEFAULT_<ALIAS>_MODEL` mapping, the phase stops (exit 1) and
reports the exact missing variable names — never values. With no
`ANTHROPIC_BASE_URL` the check is silent; a full model name passes through
untouched.

The step is **Claude-Code-only**: it exists because Claude Code resolves the
tier aliases through `ANTHROPIC_*` variables. Codex selects its session model
from its own configuration and never consumes `ANTHROPIC_*` (`docs/codex.md`,
"Configuration surface"), so under Codex the step is a documented skip, not an
enforced stop — enforcing it would halt Codex phases on variables that runtime
cannot use.

On the delegated auto path the same check runs, with the same shared
implementation, before the headless session spawns — but it warns rather than
stops (its pre-existing, deliberately preserved behavior): the session
spawns, and one that dies on a missing mapping classifies ERROR/INCOMPLETE,
never PASS. A panel that would die on its first request must fail as a loud,
actionable configuration error, never as a silent dead panel.

### Reviewer collection is foreground, same-turn, caller-bound — or the runtime is BLOCKED

A panel certifies only when every planned reviewer's result arrives
**caller-bound in the foreground of the same caller turn**: one envelope per
planned reviewer carrying `invocation_id`, `planned_reviewer_id` (the only
trusted identity), and `payload`, collected before the turn ends, then gated
and receipted (`reviewer_panel.py`; ADR 0007). The historical incident —
reviewers launched in background from a fork, the fork ending its turn,
results returning to the parent, a PASS claimed with no receipt — is pinned
by `tests/test_reviewer_dispatch_regression.py`.

**Standing rule: if a runtime or harness cannot guarantee foreground,
same-turn, caller-bound collection of every planned reviewer, that
runtime/harness is classified BLOCKED/INCOMPATIBLE for panel certification
and must never be converted into a PASS** (R4 criterion 3). A claimed verdict
without a receipt on disk is treated as not having happened; certification
without `ensure_panel_receipt` acceptance is unreachable. The runtime-level
proof for a given harness belongs to the conformance suite; the rule itself
is not conditional on it.
