# Models — tiers, not model IDs

The toolkit never names a concrete model. Every place that chooses a model
(a skill's frontmatter, an `Agent` call, an agent file, the headless recipe of
`/sdd:auto`) uses one of Claude Code's **family aliases**, and the environment
decides what each alias resolves to. That is what makes the flow provider
agnostic: the same skill text runs on Anthropic's API, on MiniMax through its
Anthropic-compatible endpoint, behind an LLM gateway, on Bedrock, or under Codex.

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

## How the environment remaps the tiers

Claude Code resolves each alias through an environment variable, and passes
any full model name through untouched when `ANTHROPIC_BASE_URL` points at a
third-party provider or gateway:

| alias | variable |
|---|---|
| `haiku` | `ANTHROPIC_DEFAULT_HAIKU_MODEL` |
| `sonnet` | `ANTHROPIC_DEFAULT_SONNET_MODEL` |
| `opus` | `ANTHROPIC_DEFAULT_OPUS_MODEL` |
| `fable` | `ANTHROPIC_DEFAULT_FABLE_MODEL` |

So a provider with a single model maps every tier to it, and the toolkit's
tiering collapses without any change to the skills. MiniMax's own Claude Code
recipe does exactly that:

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

A provider with several models maps the tiers to its own ladder (a small
model on `haiku`, a large one on `opus`). What matters is that **the mapping
lives in the user's environment**, never in the toolkit and never in a
project's `sdd/`: it describes where the user runs, not what the project
needs.

Two consequences the scripts enforce:

- `scripts/sdd_auto_outcome.py run` warns when `ANTHROPIC_BASE_URL` is set and
  the variable for the alias it is about to use is not: the alias would resolve
  to an Anthropic model ID the provider does not serve, and the session would
  fail on its first request.
- The same script refuses `haiku` as the **session** model of a headless auto
  run, whatever it maps to: Claude Code's auto permission mode is unavailable
  for that alias and the session silently starts in Manual (ADR 0005). Pass
  `sonnet` or `opus` — on a single-model provider they resolve to the same
  model anyway.

## Codex

Codex has no aliases and no `Agent` tool: a session runs on the model its
configuration names, and `run` implements inline (`docs/codex.md`). The tiers
in the skills are then documentation of intent, not selection. A project that
wants Codex to use a stronger model for `new`/`design` does it with Codex
profiles, outside the toolkit.

## Why not a `models:` block in `sdd/project.md`

Because the phase-to-tier assignment is the plugin's and the tier-to-model
mapping is the environment's (FAQ: "¿Por qué los modelos por fase son del
plugin y no por proyecto?"). A per-project block would either duplicate the
environment variables or override the plugin's tiers for everyone who opens
the project, including a teammate on a different provider.
