# LSP Catalog — code intelligence per language

Offered during the init phase based on the languages detected in the repo (or
planned in the stack, for greenfield projects). LSPs give the agent
diagnostics, go-to-definition and find-references — most valuable in medium/
large codebases; skippable for small scripts.

## How Claude Code consumes LSPs

LSP support is plugin-only (no native LSP config). The language-server
**binary must be on PATH first**; the plugin only wires the connection.
Official marketplace plugins exist for Python/TypeScript/Rust (below); other
languages need a small custom plugin with a `.lsp.json`. Plugins are
installed by the user with `/plugin install <name>` — the init agent installs
binaries (with approval) and prints the exact `/plugin` commands for the user
to run.

Note: when Claude Code runs inside VS Code/JetBrains, the IDE extension
already shares diagnostics via the built-in `ide` MCP server; LSP plugins add
value mainly for terminal/headless sessions.

## Languages

### Python
- Binary: `npm i -g pyright` (or `pip install pyright`)
- Claude Code plugin: `pyright-lsp` (official marketplace)

### TypeScript / JavaScript
- Binary: `npm i -g typescript-language-server typescript`
- Claude Code plugin: `typescript-lsp` (official marketplace)

### Rust
- Binary: `rustup component add rust-analyzer`
- Claude Code plugin: `rust-analyzer-lsp` (official marketplace)

### Go (custom plugin pattern)
- Binary: `go install golang.org/x/tools/gopls@latest`
- No official plugin — custom `.lsp.json`:

```json
{
  "go": {
    "command": "gopls",
    "args": ["serve"],
    "extensionToLanguage": { ".go": "go" }
  }
}
```

### Other languages

Same custom pattern as Go: install the server binary, create a minimal plugin
whose `.lsp.json` maps `command` + `extensionToLanguage`. Required fields
only; see the Claude Code plugins reference for optional ones
(`initializationOptions`, `diagnostics`, `restartOnCrash`, …).
