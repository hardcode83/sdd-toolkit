# MCP Catalog

Optional MCP servers offered during `/sdd:init`. Each entry is a key to merge
into the `mcpServers` object of the project's `.mcp.json`. Offer only the
ones relevant to the detected stack. Edit this file to add your own.

## github — repo, PRs, issues

Relevant when: the repo is hosted on GitHub. (Note: the `gh` CLI often suffices; offer this only if the user wants richer integration.)

```json
"github": { "type": "http", "url": "https://api.githubcopilot.com/mcp/" }
```

Auth: OAuth prompt on first use, or `Authorization: Bearer <PAT>` header.

## atlassian — Jira & Confluence

Relevant when: the team tracks work in Jira or documents in Confluence.

```json
"atlassian": { "type": "http", "url": "https://mcp.atlassian.com/v2/mcp" }
```

Auth: OAuth browser prompt on first use (`/mcp` in a session). The legacy SSE
endpoint (`mcp.atlassian.com/v1/sse`) stopped being supported on 30 June 2026 —
a project still carrying it has a dead server; `/sdd:doctor` reports it
(`SDD029`). Official plugin alternative: `atlassian@claude-plugins-official`
(offer one or the other, never both).

## playwright — browser automation / E2E

Relevant when: frontend or web app projects (verify UI changes during /sdd-run).

```json
"playwright": { "command": "npx", "args": ["@playwright/mcp@latest"] }
```

## context7 — up-to-date library docs

Relevant when: heavy use of fast-moving frameworks/libraries.

```json
"context7": { "command": "npx", "args": ["-y", "@upstash/context7-mcp"] }
```

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

## sentry — error tracking

Relevant when: the project reports errors to Sentry.

```json
"sentry": { "type": "http", "url": "https://mcp.sentry.dev/mcp" }
```

Auth: OAuth browser prompt on first use.
