# Official plugin catalog — curated for /sdd:init

Known-good plugins from `claude-plugins-official` (pre-registered in every
Claude Code install), offered by `/sdd:init` when relevant to the detected
stack. The agent cannot query the marketplace programmatically (no search
CLI, no public marketplace.json) — this curated list is the source, and the
user runs the install commands. Browsable catalog: claude.com/plugins, or
the `/plugin` Discover tab.

Maintenance note: entries can drift as the official catalog evolves — treat
names as best-effort and tell the user to check `/plugin` if an install
fails. Edit this file to add/correct entries.

## Code intelligence (LSPs)

Covered by `lsp-catalog.md` — don't offer twice.

## Security

- **`security-guidance`** — automatic security review guidance on changes.
  Relevant: almost always. Note the overlap with our `sdd-security` panel
  reviewer: the panel verifies *your* `security.md` rules at section/feature
  gates; this plugin adds generic guidance outside the SDD cycle too. They
  compose, but mention the overlap so the user chooses consciously.

## Development workflows

- **`commit-commands`** — commit-message helpers. Relevant: teams with commit
  conventions not already covered by the SDD flow's own commit patterns.
- **`pr-review-toolkit`** — PR review helpers. Relevant: teams reviewing PRs
  in GitHub (pairs well with `/sdd:auto`'s PR-per-feature output).

## External integrations

- **GitHub / Jira / Slack / Figma** integration plugins. Relevant: when the
  team lives in those tools. ⚠️ Overlap warning: our `mcp-catalog.md` offers
  some of the same integrations as raw MCP servers — offer ONE of the two
  per tool (plugin if it exists officially, raw MCP otherwise), never both.

## How to install (user runs these; agents can't)

```
/plugin install <name>@claude-plugins-official
```
