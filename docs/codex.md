# SDD Toolkit with OpenAI Codex (experimental)

This adapter exposes the existing SDD skills to Codex without copying the
methodology or replacing the Claude Code plugin. Claude Code and Codex operate
on the same `sdd/` Markdown artifacts.

## Installation

The experiment is prepared for a local checkout. Register that checkout as a
non-default marketplace, install the plugin, and then start a new Codex thread:

```bash
codex plugin marketplace add /absolute/path/to/sdd-toolkit
codex plugin add sdd-toolkit@sdd-toolkit-experimental
```

The manifest points directly to the repository's existing `skills/` directory.
Cloning the repository alone does not activate those skills; the marketplace
and plugin must be installed. This experiment did not modify or install
anything in the user's global Codex configuration during validation.

Claude Code installation and `/sdd:*` commands remain unchanged.

## Invocation

Invoke a phase explicitly with `$<skill>`. Some Codex clients may display the
same skill in their picker as `sdd-toolkit:<skill>`.

| Phase | Codex invocation | Gate or qualification |
|---|---|---|
| Status | `$status` | Read-only. |
| New | `$new <feature> [seed.md]` | Creates only `proposal.md`; approve it before continuing. |
| Design | `$design <feature>` | Run after proposal approval; approve `design.md`. |
| Tasks | `$tasks <feature>` | Run after proposal/design approval; approve `tasks.md`. |
| History | `$history [feature or question]` | Read-only archive query with source citations. |
| Init | `$init [plan.md]` | Core scaffold is validated; decline unsupported Claude extras when using Codex. |
| Run | `$run <feature> solo` | Basic sequential execution is validated only in explicit `solo` mode. |
| Archive | `$archive <feature>` | Validated for a completed, unblocked change without metrics or roadmap updates. |

The approval gates remain part of the workflow. Do not chain `new`, `design`,
`tasks`, `run`, or `archive` without the same explicit approvals required by
Claude Code.

## Compatibility matrix

| Capability | Status | Evidence and boundary |
|---|---|---|
| Direct use of shared `skills/` | Experimental | The Codex plugin manifest validates and references `./skills/`; no phase logic is copied. |
| Shared proposal/design/task/spec formats | Verified | Codex consumed a Claude-compatible proposal, produced design/tasks, implemented it, and archived it without conversion. |
| `status` | Verified | Read-only execution against a temporary fixture. |
| `new` | Verified | Produced only a proposal and stopped at its approval gate. |
| `design` | Verified | Resumed from a persisted proposal in a fresh session. |
| `tasks` | Verified | Resumed from persisted proposal/design files and covered all requirement IDs. |
| `history` | Verified | Read an archived change and current spec, cited the record, and reported current validity without writes. |
| `init` core scaffold | Partially supported | Created `sdd/project.md`, `sdd/README.md`, specs/archive directories, and selected steering docs. Planning ingestion, re-init/merge, baselines, and extras remain unverified. |
| `run` sequential `solo` | Partially supported | Implemented every task in order, ran seven `unittest` tests, and checked tasks only after verification. The Claude review panel was deliberately skipped. |
| `archive` basic path | Partially supported | Re-verified tests, created a living spec, and moved the change to the dated archive. Metrics, roadmap, BLOCKED override, and existing-spec merge paths remain unverified. |
| `review`, `auto`, `diagram` | Unverified | Outside this experiment. |
| Claude reviewer panel | Unsupported | Claude agent types and project `.claude/agents/` reviewers were not adapted. |
| Tournament mode | Unsupported | Claude Agent calls, model roles, and isolated-worktree tournament orchestration were not adapted. |
| Claude telemetry | Unsupported | No Codex equivalent was added for Claude OTel variables or per-phase usage scripts. |
| Claude hooks and RTK rewrite | Unsupported | The Claude `PreToolUse` hook was neither enabled nor validated in Codex. |

## Known limitations

- The existing skills resolve shared files through `${CLAUDE_PLUGIN_ROOT}`.
  Installed-plugin compatibility must provide that value. Repo-local fixture
  validation supplied it explicitly.
- Claude model names in skill frontmatter do not select Codex models. Codex
  uses the model configured for its session.
- `AskUserQuestion` has no identical Codex primitive. Normal questions preserve
  the verified phase gates, but advanced multi-select interactions are not
  guaranteed to behave identically.
- `init` still uses shared Claude-oriented scaffold text and contains optional
  behavior for `CLAUDE.md`, `.claude/settings.json`, Claude reviewers, MCP/LSP
  suggestions, telemetry, and RTK. The validated Codex path explicitly declined
  all those extras.
- Use `$run <feature> solo` for the validated path. Default `run` expects the
  Claude architect/security/QA panel. Silent substitution with a different
  review policy would change the methodology and is not part of this adapter.
- Basic archive interoperability is established, but archive edge cases and
  team policies still require human review.
- The local marketplace installation commands are documented from the Codex
  CLI contract, but global installation was intentionally not performed during
  the experiment.

## Token-efficient operation

The phase skills are prompt-driven, so cumulative input can grow across every
tool/model round in one execution. To keep usage controlled:

1. Keep `sdd/project.md` concise and filled with exact commands; avoid
   placeholder content that triggers extra discovery.
2. Invoke one phase per fresh thread and name the feature explicitly.
3. Provide an explicit read allowlist: project file, current change artifacts,
   affected source/tests, phase skill, rules, and the one required template.
4. Tell Codex not to read full README files or inventory the repository unless
   the phase genuinely requires it.
5. Avoid repeating complete proposal/design/task contents in tool output.
6. Prefer `$run <feature> next 1 solo` or a numbered section for large changes;
   a full run can accumulate context at every task and test checkpoint.
7. Use `status` and `history` as read-only sessions with narrowly named sources.
8. Stop after one capacity failure and change the model or reduce scope before
   retrying.
9. Treat cached-input counts as repeated context, not unique context size; high
   cached input still has latency and cost implications.

## Uninstall and revert

Remove the installed plugin first, then the configured marketplace:

```bash
codex plugin remove sdd-toolkit@sdd-toolkit-experimental
codex plugin marketplace remove sdd-toolkit-experimental
```

Start a new Codex thread after uninstalling. These commands affect only the
Codex adapter; they do not remove the Claude Code plugin or project `sdd/`
artifacts.

To revert the source experiment before it is committed, remove only:

```text
.codex-plugin/plugin.json
.agents/plugins/marketplace.json
docs/codex.md
```

Do not delete project `sdd/` directories: they are shared persistent state and
remain readable by Claude Code.

## Readiness verdict

The adapter is usable for controlled daily work with `status`, `new`, `design`,
`tasks`, `history`, core-only `init`, sequential `run ... solo`, and the basic
archive path. It is not yet a full daily-use replacement for the Claude Code
workflow when reviewer panels, tournament mode, telemetry, hooks, automatic
mode, init extras, or archive edge cases are required.
