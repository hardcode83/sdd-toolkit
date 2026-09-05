# Official plugin catalog — curated for /sdd:init

Known-good plugins from `claude-plugins-official` (pre-registered in every
Claude Code install), offered by `/sdd:init` when relevant to the detected
stack. The agent cannot query the marketplace programmatically — this curated
list is the source, and the user runs the install commands. Browsable catalog:
claude.com/plugins, or the `/plugin` Discover tab. Install counts below are the
public directory's, mid-2026, as a proxy for "battle-tested" — not a ranking.

Maintenance note: entries drift as the official catalog evolves — treat names
as best-effort and tell the user to check `/plugin` if an install fails. Edit
this file to add/correct entries. Last full review: September 2026.

**What a plugin costs.** A plugin's skills add one description line each to
every request; its hooks run on every matching event and whatever they inject
is paid on every occurrence; its MCP servers follow the rules in
`mcp-catalog.md`. Say the cost when you offer the plugin, so the user chooses
knowingly.

**Codex.** Skills (`SKILL.md`) follow the Agent Skills spec and carry over to
Codex; hooks and LSP plugins do not. Each entry says which.

## Code intelligence (LSPs)

Covered by `lsp-catalog.md` — don't offer twice.

## Skills — how the agent works, on demand

- **`frontend-design`** (Anthropic, 1.1M installs — the most installed plugin
  in the directory). A single skill (~2k words, no tools) that fires when the
  user asks for UI: it makes the agent commit to a direction first — a token
  set (4–6 colours), typography, one memorable element, restraint elsewhere —
  and checks the plan against the known "AI defaults" before writing code.
  Relevant: any project with a frontend. **Overlap to state:** the skill pushes
  toward *distinctive*; a project with a design system needs *consistent*.
  `sdd/steering/frontend.md` (or the design system doc) wins — say so when
  offering, and make sure the steering doc names the tokens the skill would
  otherwise invent. Codex: portable.
- **`webapp-testing`** (Anthropic, repo `anthropics/skills`, Apache 2.0). Not
  in the official marketplace — a skill in the example bundle: Playwright in
  Python plus `with_server.py`, which brings up back + front, runs a script and
  returns only its result. This is the cheapest way for `/sdd:run`'s per-section
  implementer to verify a web change: the DOM and the screenshots stay in the
  script, thirty lines come back. Relevant: web projects. Install either way:
  - `/plugin marketplace add anthropics/skills` then
    `/plugin install example-skills@anthropic-agent-skills` — brings the whole
    bundle (15 skills, one description line each on every request), or
  - copy `skills/webapp-testing/` into the project's `.claude/skills/` — only
    that one, versioned with the repo (recommended). Codex: portable.
- **`hookify`** (Anthropic). Turns a rule written in markdown into a hook that
  blocks the behaviour deterministically ("never commit to main", "never run
  `rm -rf` outside the worktree", "no `console.log` in `src/`"). Relevant: any
  project whose steering has *mechanical* rules — those are the ones the panel
  should not have to spend a reviewer on. Complements the panel, which verifies
  rules of judgement. Codex: the generated hooks are Claude Code only.
- **`code-simplifier`** (Anthropic, 285k). A pass that simplifies code just
  written, keeping behaviour. Relevant: optional, before `/sdd:review`. State
  the overlap: it does not replace the `LOCAL_VERIFIED` gate or the panel; it
  is a cleanup the panel then reviews. Codex: portable.

## Security

- **`security-guidance`** (Anthropic, 176k) — a PreToolUse hook on every
  Write/Edit that injects a reminder of eight vulnerability classes (command
  injection, `eval`, XSS sinks, pickle, `os.system`…) so the agent self-checks
  before writing. Relevant: almost always. Cost to state: the reminder is paid
  on **every edit**. Overlap with our `sdd-security` panel reviewer: the panel
  verifies *your* `security.md` rules at section/feature gates; this plugin adds
  generic guidance outside the SDD cycle too. They compose, but mention the
  overlap so the user chooses consciously. Codex: hook, not portable.
- **`semgrep`** — static analysis with Semgrep rules. Relevant: projects that
  already run Semgrep in CI and want the same findings during `run`.

## Development workflows

- **`commit-commands`** (Anthropic, 145k) — commit-message helpers. Relevant:
  teams with commit conventions not already covered by the SDD flow's own
  commit patterns.
- **`pr-review-toolkit`** (Anthropic, 97k) — PR review helpers. Relevant:
  teams reviewing PRs in GitHub (pairs well with `/sdd:ship`'s PR-per-feature
  output).

## Code navigation

- **`serena`** (81k) — symbol-level tools for large codebases; see the last
  section of `lsp-catalog.md` for when it earns its place.

## External integrations

- GitHub / Atlassian / Linear / Figma / Slack / Sentry / Supabase / Neon /
  Vercel plugins exist officially. Relevant: when the team lives in those
  tools. ⚠️ Overlap warning: `mcp-catalog.md` offers some of the same
  integrations as raw MCP servers — offer ONE of the two per tool (plugin if it
  exists officially, raw MCP otherwise), never both.

## Not offered, and why

The init must not offer these, however popular. Say why if the user asks.

- **`superpowers`** (1.0M installs, 280k GitHub stars) — a complete
  methodology: brainstorming → writing-plans → executing-plans →
  subagent-driven development → TDD → code review. It competes phase by phase
  with `new`/`design`/`tasks`/`run`, and its SessionStart hook injects the
  `using-superpowers` skill (~1.3k tokens, currently twice because of a known
  bug) on every startup, `/clear` and compaction. Two methodologies in one
  session override each other; a project on SDD has already chosen.
- **`feature-dev`** (Anthropic, 256k) — a seven-phase feature workflow
  (discovery, exploration, questions, architecture, implementation, review,
  summary) with its own explorer/architect/reviewer agents. It is SDD without
  specs or archive. Same reason.
- **`ralph-loop`** (Anthropic) — blocks the session from ending until the task
  is "done". Incompatible with the approval gates (shared rule 3).
- **`code-review`** (Anthropic, 439k) — five parallel agents on a PR, posts to
  GitHub. Duplicates the panel. Could serve as a second opinion after
  `/sdd:ship` if a team asks for it explicitly; not a default.
- **`claude-code-setup`**, **`claude-md-management`** — the first recommends
  MCPs/hooks/skills per stack (what this init does); the second manages
  CLAUDE.md (the init writes a pointer and keeps rules in `sdd/steering/`).
  Useful to maintainers of *this* catalog as a cross-check; not for consumers.

## How to install (user runs these; agents can't)

```
/plugin install <name>@claude-plugins-official
```
