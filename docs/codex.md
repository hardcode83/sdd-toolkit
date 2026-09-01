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
scripts/codex-adapter-install.sh
```

The adapter manifest's `version` tracks `.claude-plugin/plugin.json` — CI fails
when they diverge, because the adapter exposes exactly those skills. Bump both in
the same commit.

The manifest points directly to the repository's existing `skills/` directory.
Cloning the repository alone does not activate those skills; the marketplace
and plugin must be installed.

The third step is required, not optional. The shared skills and the PreToolUse
hook reference files through `${CLAUDE_PLUGIN_ROOT}` — a variable Claude Code
sets but Codex neither substitutes in skill text nor exports to the shell.
`codex-adapter-install.sh` resolves the *installed* plugin root (the version is
read at run time, never hardcoded) and writes it into `~/.codex/config.toml`
under `shell_environment_policy.set`, so Codex's shell resolves the variable for
both the skills' file reads and the hook. Re-run it after every `codex plugin`
update so the path tracks the new version. It is idempotent and refuses to
clobber a pre-existing `[shell_environment_policy]` table.

The installed `skills/reviewer-panel/` resource is self-contained: it contains
the canonical core registry, shared planner/result gate, and native Codex
dispatch instructions. Native Codex panels spawn architect, security, and QA
reviewers in one parallel batch, bind handles to expected identities, wait and
collect exactly one in-scope structured result per reviewer, and fail closed
on unavailable or unverifiable results. No `~/.codex/agents`, copied prompts,
symlinks, or project-local Codex configuration is needed. Existing
`.claude/agents/sdd-review-*.md` files remain additive project reviewers for
both runtimes, and MiniMax continues through the Claude route.
Legacy Claude frontmatter (`description`, `model`, and `tools`) remains
accepted; shared-planner metadata `phases` and `applies_to` is optional for
those reviewers. Claude model/tool declarations are not Codex model selection
or capability grants.

Verified: with the block in place, `printenv CLAUDE_PLUGIN_ROOT` inside a Codex
shell returns the installed root, `cat "${CLAUDE_PLUGIN_ROOT}/rules.md"`
succeeds, and no PreToolUse hook error appears on Bash tool calls. Without it,
all three fail (the shell expands the unset variable to `/rules.md`).

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
| Run | `$run <feature>` | Default run uses the shared logical reviewer panel; `solo` remains an explicit bypass with no panel PASS. |
| Archive | `$archive <feature>` | Requires objective merged-PR evidence; the new merge-gated path is not yet validated under Codex. |

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
| `run` reviewer panel | Supported | Default run uses the shared planner, native Codex panel handoff, and deterministic fail-closed result gate. `solo` is the explicit no-panel bypass. |
| `archive` merge-gated path | Unverified | The former pre-merge basic path is obsolete. Shared skills now require `STATE.md` plus objective `gh` merge evidence before specs, roadmap, and archive writes. |
| Roadmap graph (`scripts/sdd_roadmap.py`) | Expected to work, unverified | Python 3 stdlib and read-only, like `sdd-doctor.py`, so nothing Claude-specific is involved: `status`'s frontier/waves/critical-path views and the `SDD018`-`SDD023` checks are one subprocess call. Not exercised under Codex. |
| `review`, `auto`, `diagram` | `review` and `auto` supported through the shared fail-closed panel; `diagram` unchanged | Native Codex panel uses installed reviewer-panel resources. |
| Claude reviewer panel | Supported | Existing Claude agent paths remain compatibility surfaces; the shared logical plan validates core parity and legacy project reviewers. |
| Worktree isolation | Partially supported | `scripts/sdd_session.py` is Python 3 stdlib and works unchanged, so `check` / `policy` / `claim` / `resolve` / `orphans` all answer correctly. What is missing is the `EnterWorktree` tool: nothing can switch the session's working directory, so isolation is **manual** — `git worktree add .claude/worktrees/sdd+<feature> -b sdd/<feature>`, then run the phase from that directory and `claim` it from there so later phases can `resolve` it. Shared rule 10's branch guard in `run` still applies and still protects the merge evidence. |
| `isolation: always` | Partially supported, as a handoff | The policy is read correctly (`sdd_session.py --root . policy`), and it must never be silently ignored. Since the session cannot enter the worktree, a phase that has to isolate **creates it, binds it (`claim <feature> --worktree <path>`) and stops**, telling the user to re-run the phase from that directory; under `/sdd:auto` that is a `BLOCKED.md` entry with the resume command. Continuing in the main clone would defeat the policy the project declared (ADR 0002 D5). |
| Tournament mode | Unsupported | Claude Agent calls, model roles, and isolated-worktree tournament orchestration were not adapted. |
| Claude telemetry | Unsupported | No Codex equivalent was added for Claude OTel variables or per-phase usage scripts. |
| Claude `PreToolUse` hook (RTK rewrite) | Non-fatal | Codex ingests `hooks/hooks.json` and enables the hook. The command is now guarded (`[ -x "$h" ] && exec "$h"; exit 0`), so it no-ops instead of failing when the path is unresolved; with the install script it resolves and runs (`rtk` absent → clean no-op). RTK rewrite itself is not exercised under Codex. |

## Known limitations

- `review`, `ship`, `archive`, `status` and `history` declare Claude-only
  frontmatter (`context: fork`, `background`, `effort`, alongside the existing
  `model`). Codex ignores those keys and runs the skill inline, as it always did.
  The skills are written so that nothing depends on the fork: every question a
  forked phase cannot ask ends in a `HANDOFF` block (shared rule 11), which is
  also the right shape for Codex, where `AskUserQuestion` never existed. Under
  Codex the caller and the phase are the same session, so the `HANDOFF` is
  simply the gate and the step 9 close of `archive` runs in that same session.

- The existing skills resolve shared files through `${CLAUDE_PLUGIN_ROOT}`, which
  Codex does not provide on its own (confirmed: unset in the shell, and not
  substituted in skill text). `scripts/codex-adapter-install.sh` supplies it via
  `shell_environment_policy.set` — run it at install and after every update.
  Without that step the phases fail to read `rules.md` and templates.
- Claude model names in skill frontmatter do not select Codex models. Codex
  uses the model configured for its session.
- `AskUserQuestion` has no identical Codex primitive. Normal questions preserve
  the verified phase gates, but advanced multi-select interactions are not
  guaranteed to behave identically.
- `init` still uses shared Claude-oriented scaffold text and contains optional
  behavior for `CLAUDE.md`, `.claude/settings.json`, Claude reviewers, MCP/LSP
  suggestions, telemetry, and RTK. The validated Codex path explicitly declined
  all those extras.
- Default `$run`, `$review`, and `$auto` use the shared architect/security/QA
  panel. `$run <feature> solo` remains the explicit bypass and cannot record a
  panel PASS. A missing or invalid reviewer result fails closed.
- Merge-gated archive interoperability remains governed by the existing
  lifecycle contract; archive still requires objective merged-PR evidence.
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

The adapter is usable for controlled daily work with the shared reviewer panel
through `run`, `review`, and `auto`; merge-gated archive, tournament mode,
telemetry, hooks, and init extras retain their documented boundaries.
