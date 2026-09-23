# Models — tiers, not model IDs

The toolkit never names a concrete model. Every place that chooses a model
(a skill's frontmatter, an `Agent` call, an agent file, the headless recipe of
`/sdd:auto`) uses one of Claude Code's **family aliases**, and the environment
decides what each alias resolves to. That is what makes the flow provider
agnostic: the same skill text runs on Anthropic's API, on Kimi or MiniMax
through their Anthropic-compatible endpoints, behind an LLM gateway, on
Bedrock, or under Codex.

The runtime the aliases live in matters more than the provider behind it.
This file documents the **Anthropic-compatible group**: the Claude Code
runtime with Anthropic, Kimi, or MiniMax as provider. Codex (the OpenAI
runtime) has a different configuration surface and is documented from its own
evidence in `docs/codex.md` and `references/runtime-provider.md` — the two
groups are deliberately not one recipe, because what Codex consumes is not
what Claude Code consumes.

## The four tiers

| alias | tier | what the toolkit uses it for |
|---|---|---|
| `haiku` | fast | read-only phases run in a fork (`status`, `history`); background helpers |
| `sonnet` | standard | orchestrators (`run`, `auto`), implementers, per-section reviewers, `review`/`ship`/`archive` forks |
| `opus` | strong | `new` and `design` (the thinking phases), sections marked `<!-- hard -->`, `sdd-security` at feature scale, the second fix round, `tournament` |
| `fable` | strongest | reserved: the optional arbiter of ADR 0006, opt-in and off by default |

**Every `Agent` call names its tier explicitly.** Measured on the first real
auto run (2026-09-05): the orchestrator's `Agent` calls carried no `model`, so
each implementer inherited the session model. In a Sonnet session that was
harmless; in an Opus session every implementer and every fix round would have
run on Opus. The skill text says which tier each launch gets; the call must
carry it.

## The Anthropic-compatible group

Claude Code as runtime, any of Anthropic / Kimi / MiniMax as provider. The
mechanism is the same for all three: Claude Code resolves each alias through
an environment variable, and passes any full model name through untouched,
when `ANTHROPIC_BASE_URL` points at a third-party provider or gateway:

| alias | variable |
|---|---|
| `haiku` | `ANTHROPIC_DEFAULT_HAIKU_MODEL` |
| `sonnet` | `ANTHROPIC_DEFAULT_SONNET_MODEL` |
| `opus` | `ANTHROPIC_DEFAULT_OPUS_MODEL` |
| `fable` | `ANTHROPIC_DEFAULT_FABLE_MODEL` |

With **native Anthropic** (no `ANTHROPIC_BASE_URL`), no recipe is needed: the
aliases resolve to Anthropic's own model IDs. The recipes below are for the
third-party providers of this group.

So a provider with a single model maps every tier to it, and the toolkit's
tiering collapses without any change to the skills. What matters is that
**the mapping lives in the user's environment**, never in the toolkit and
never in a project's `sdd/`: it describes where the user runs, not what the
project needs. A provider with several models maps the tiers to its own
ladder (a small model on `haiku`, a large one on `opus`).

### Provider recipes

Each recipe names the environment variables to set and the aliases each tier
resolves to through them. Recipes rot — providers change endpoints and model
names — so each records its observation date and the verification command
that re-checks the alias mapping before a phase launch.

Verify a mapping with (from `scripts/provider_profile.py`, section 1 of the
foundation change):

```bash
python3 scripts/provider_profile.py check --aliases sonnet,opus
```

Exit 0 means every alias the phase will launch is mapped; exit 1 names the
exact missing `ANTHROPIC_DEFAULT_<ALIAS>_MODEL` variable. With
`ANTHROPIC_BASE_URL` unset the check is silent — native Anthropic needs no
mapping — and a full model name passes through with no check at all.

#### MiniMax

Observed: 2026-09-05. MiniMax's own Claude Code recipe maps every tier to its
single model, `MiniMax-M3`, served by the Anthropic-compatible endpoint:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic",
    "ANTHROPIC_AUTH_TOKEN": "<key>",
    "ANTHROPIC_MODEL": "MiniMax-M3",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "MiniMax-M3",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "MiniMax-M3",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "MiniMax-M3"
  }
}
```

- `ANTHROPIC_BASE_URL` — MiniMax's Anthropic-compatible endpoint.
- `ANTHROPIC_AUTH_TOKEN` — the MiniMax API credential (the third-party-token
  role of Claude Code's credential variables; `ANTHROPIC_API_KEY` is the
  alternative role).
- `ANTHROPIC_MODEL` — the session model.
- `ANTHROPIC_DEFAULT_<ALIAS>_MODEL` — every tier maps to `MiniMax-M3`, so the
  toolkit's tiering collapses onto the one model MiniMax serves through this
  endpoint.

Verify: `python3 scripts/provider_profile.py check --aliases sonnet,opus`
(exit 0 expected with the block above).

#### Kimi

Observed: 2026-09 — a 5-hour usage window and Claude Code's Auto Mode
classifier notice arriving via `api.kimi.com` (see "Quota semantics" below).
The exact endpoint path, the Kimi model name as served by the gateway, and
the credential variable Kimi expects are **not evidenced in this repository**
and are marked `unknown`; they must be copied from Kimi's own
Anthropic-compatible documentation and confirmed with the verification
command before a phase launch.

Set, in the Claude Code environment:

- `ANTHROPIC_BASE_URL` — Kimi's Anthropic-compatible endpoint. The observed
  host is `api.kimi.com`; the path below it is `unknown`.
- The credential variable — `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY`,
  holding the Kimi API key. Which role Kimi's endpoint expects is `unknown`.
- `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`,
  `ANTHROPIC_DEFAULT_HAIKU_MODEL` — each set to the Kimi model the tier
  should resolve to. The model name is `unknown` here; on a single-model
  mapping all three carry the same name, as in the MiniMax recipe.

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.kimi.com/<path unknown — copy from Kimi's docs>",
    "ANTHROPIC_AUTH_TOKEN": "<kimi key>",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "<kimi model>",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "<kimi model>",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "<kimi model>"
  }
}
```

Verify: `python3 scripts/provider_profile.py check --aliases sonnet,opus`
(exit 0 expected once every alias above is set).

## Quota semantics (observed 2026-09)

`--max-budget-usd` — the flag the headless auto recipe passes to the delegated
session (`scripts/sdd_auto_outcome.py`) — is a per-session USD ceiling Claude
Code enforces by estimating token cost. It protects only quotas denominated
in per-token USD. Two observed behaviors on this group are **not** covered by
it:

- **Kimi bills by usage windows, not per-token USD.** Observed 2026-09: Kimi
  enforces a 5-hour usage window on the model. Window quota is spent whether
  or not the session is under its USD budget, so `--max-budget-usd` does not
  protect it: a session well inside budget can still be refused the moment
  the window is exhausted.
- **Auto Mode classifier requests consume provider quota on non-Anthropic
  gateways.** Observed 2026-09: Claude Code surfaced a notice that its Auto
  Mode classifier requests are sent to the configured gateway — `api.kimi.com`
  in the observation — and therefore spend Kimi quota in addition to whatever
  the phase's own work consumes. The classifier traffic is outside the
  phase's `--max-budget-usd` accounting in exactly the same way.

No optimization is prescribed here. Changing how the toolkit invokes the
runtime — batching, caching, classifier routing, flag tuning — is out of
scope until a conformance measurement exists behind it (the proposal of this
change lists those as follow-ups, not decisions).

## Codex

Codex has no aliases and no `Agent` tool: a session runs on the model its own
configuration names, and `run` implements inline (`docs/codex.md`). The
tiers in the skills are then documentation of intent, not selection; the
`ANTHROPIC_*` variables and the alias recipes above are Claude Code
configuration, not Codex configuration. A project that wants Codex to use a
stronger model for `new`/`design` does it with Codex profiles, outside the
toolkit — the evidence is in `docs/codex.md` ("Configuration surface") and
the layer model is in `references/runtime-provider.md`.

## Why not a `models:` block in `sdd/project.md`

Because the phase-to-tier assignment is the plugin's and the tier-to-model
mapping is the environment's (FAQ: "¿Por qué los modelos por fase son del
plugin y no por proyecto?"). A per-project block would either duplicate the
environment variables or override the plugin's tiers for everyone who opens
the project, including a teammate on a different provider.

Two consequences the scripts enforce, for every provider of this group:

- `scripts/sdd_auto_outcome.py run` (and the phase preflight step of
  `skills/run`, `skills/review`, `skills/auto`) warns when
  `ANTHROPIC_BASE_URL` is set and the variable for the alias it is about to
  use is not: the alias would resolve to an Anthropic model ID the provider
  does not serve, and the session would fail on its first request.
- The same script refuses `haiku` as the **session** model of a headless auto
  run, whatever it maps to: Claude Code's auto permission mode is unavailable
  for that alias and the session silently starts in Manual (ADR 0005). Pass
  `sonnet` or `opus` — on a single-model provider they resolve to the same
  model anyway.
