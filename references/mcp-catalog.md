# MCP Catalog

Optional MCP servers offered during `/sdd:init`. Each entry is a key to merge
into the `mcpServers` object of the project's `.mcp.json`. Offer only the
ones relevant to the detected stack. Edit this file to add your own.

**What an MCP server costs.** Since Claude Code 2.1.215 tool schemas are
discovered on demand (Tool Search), so a server that sits unused costs almost
nothing per request. The cost is paid when it is *used*: its outputs land in
the conversation (`MAX_MCP_OUTPUT_TOKENS`, 25k by default), and a server with
many tools still dilutes discovery. Two rules follow: offer a server only when
the stack will actually call it, and scope it to the project (`.mcp.json`),
never globally — a server that belongs to another project is approval prompts
and noise here. When the same integration exists as an official plugin
(`plugin-catalog.md`), offer ONE of the two, never both.

**Codex.** Each entry says whether it carries over. Codex reads MCP servers from
`~/.codex/config.toml` (`[mcp_servers.<name>]`), not from `.mcp.json`; the
`command`/`args`/`url` are the same, the file is not.

## github — repo, PRs, issues

Relevant when: the repo is hosted on GitHub. The `gh` CLI covers almost all of
it and the flow's own `ship`/`archive` already use `gh`; offer this only if the
user wants richer integration (PR review context, issue search). It is the
server with the most tools, so it is the one that most dilutes discovery.

```json
"github": { "type": "http", "url": "https://api.githubcopilot.com/mcp/" }
```

Auth: OAuth prompt on first use, or `Authorization: Bearer <PAT>` header.
Official plugin alternative: `github@claude-plugins-official`. Codex: same URL.

## atlassian — Jira & Confluence

Relevant when: the team tracks work in Jira or documents in Confluence.

```json
"atlassian": { "type": "http", "url": "https://mcp.atlassian.com/v2/mcp" }
```

Auth: OAuth browser prompt on first use (`/mcp` in a session). The legacy SSE
endpoint (`mcp.atlassian.com/v1/sse`) stopped being supported on 30 June 2026 —
a project still carrying it has a dead server; `/sdd:doctor` reports it
(`SDD029`). Official plugin alternative: `atlassian@claude-plugins-official`
(offer one or the other, never both). Codex: same URL.

## browser — verify UI changes, debug in a real browser

Relevant when: frontend or web app projects. Three tools, three jobs — offer the
one that matches what the project needs, not all three:

| Need | Tool | Why this one |
|---|---|---|
| Verify a change works, E2E, CI | **Playwright** — plugin `playwright@claude-plugins-official`, or the raw server below | Deterministic, cross-browser (Chromium/Firefox/WebKit), the only one to point at CI. 23 tools; a full test run through the MCP has been measured at ~114k tokens, so in `/sdd:run` prefer scripts that return a summary (the `webapp-testing` skill in `plugin-catalog.md`) over driving the browser tool by tool. |
| Profile performance, inspect network, Lighthouse, Core Web Vitals | **Chrome DevTools MCP** — plugin `chrome-devtools-mcp@claude-plugins-official` (Google) | 29 tools over the DevTools Protocol: traces, memory snapshots, network, console with stack traces, device emulation. Chromium-only. For debugging, not for test suites. |
| Interactive debugging in the user's own logged-in browser | **Claude in Chrome** — `claude --chrome`, native | No server to install: the Chrome extension shares the user's sessions and cookies (works on apps behind login). Needs a direct Anthropic plan and `/login`; unavailable with an API key, Bedrock or Vertex. Do **not** enable it by default (`/chrome` → "Enabled by default"): the docs warn it raises context on every session; pass `--chrome` when needed. |

```json
"playwright": { "command": "npx", "args": ["@playwright/mcp@latest"] }
```

Codex: Playwright and Chrome DevTools carry over as MCP servers; Claude in
Chrome is Claude Code only.

## context7 — up-to-date library docs

Relevant when: the stack leans on fast-moving frameworks or young SDKs where
the model's training data is stale (Next.js, Prisma, Tailwind, agent SDKs…).
For stable stacks (Django, Spring, the standard library) `WebFetch` on the
official docs or a project's `llms.txt` does the same job for free — don't
offer it there.

Two tools (`resolve-library-id`, `query-docs`): idle cost ≈ 0. The costs are
per use: responses can be large, and since January 2026 the free tier is
**1,000 requests/month, 60/hour** (paid plan from 10 USD/month). An API key is
required for usable limits.

```json
"context7": { "type": "http", "url": "https://mcp.context7.com/mcp", "headers": { "Authorization": "Bearer ${CONTEXT7_API_KEY}" } }
```

Official plugin alternative: `context7@claude-plugins-official` (offer one or
the other). Key: `context7.com/dashboard`, or `npx ctx7 setup --claude`. If the
user wants it used without asking, Upstash documents a one-line CLAUDE.md
rule ("Always use Context7 when I need library/API documentation, code
generation, setup or configuration steps") — offer it only if they accept the
per-use cost. Alternatives when the limit hurts: Neuledge Context (local,
Apache 2.0), Docfork (MIT), GitMCP (free, reads the docs of a GitHub repo),
Ref (responses capped ~5k tokens). Codex: same URL.

## postgres — read-only DB inspection

Relevant when: the project uses PostgreSQL and schema questions come up often.

```json
"postgres": { "command": "npx", "args": ["-y", "@bytebase/dbhub", "--dsn", "postgresql://readonly:PASSWORD@localhost:5432/DBNAME"] }
```

Replace the DSN; use a read-only role. This is the server the Claude Code docs
recommend for database queries. The former reference server
(`@modelcontextprotocol/server-postgres`) is archived upstream with an explicit
"no security guarantees" notice — a project still launching it is flagged by
`/sdd:doctor` (`SDD029`). When the database is hosted on Supabase or Neon,
prefer their official plugins (`supabase`, `neon`) over a raw connection.
Codex: same command.

## sentry — error tracking

Relevant when: the project reports errors to Sentry.

```json
"sentry": { "type": "http", "url": "https://mcp.sentry.dev/mcp" }
```

Auth: OAuth browser prompt on first use. Official plugin alternative:
`sentry@claude-plugins-official`. Codex: same URL.

## linear — issue tracking

Relevant when: the team plans in Linear (not Jira). Offer as the official
plugin `linear@claude-plugins-official`; there is no need for a raw entry.
Codex: `https://mcp.linear.app/mcp` as an MCP server.

## figma — design files and components

Relevant when: a frontend project implements designs that live in Figma
(pairs with `frontend-design` in `plugin-catalog.md`: one gives the referent,
the other the discipline). Offer as the official plugin
`figma@claude-plugins-official`. Codex: Figma's remote MCP server.

## slack — notifications

Relevant when: the team wants `ship`/PR events or `BLOCKED` entries surfaced in
a channel. Optional; most teams get this from GitHub's own Slack app. Official
plugin `slack@claude-plugins-official`, or:

```json
"slack": { "type": "http", "url": "https://mcp.slack.com/mcp" }
```

## Not offered, and why

- `filesystem`, `memory`, `sequential-thinking`: redundant with Claude Code's
  own Read/Edit/Glob/Grep, with CLAUDE.md + auto-memory, and with extended
  thinking. Every ranking that tests them says the same.
- Web search servers (Exa, Firecrawl…): `WebSearch`/`WebFetch` are built in;
  offer one only when a project genuinely needs scraping at scale.
