# LSP Catalog — code intelligence per language

Offered during the init phase based on the languages detected in the repo (or
planned in the stack, for greenfield projects). LSPs give the agent
diagnostics, go-to-definition and find-references — most valuable in medium/
large codebases; skippable for small scripts.

## How Claude Code consumes LSPs

LSP support is plugin-only (no native `settings.json` key). The language-server
**binary must be on PATH first**; the plugin only wires the connection. The
official marketplace ships a plugin for every language below; anything else
needs a small custom plugin with a `.lsp.json`. Plugins are installed by the
user with `/plugin install <name>@claude-plugins-official` — the init agent
installs binaries (with approval) and prints the exact `/plugin` commands for
the user to run.

Two caveats to say out loud:

- When Claude Code runs inside VS Code/JetBrains, the IDE extension already
  shares diagnostics via the built-in `ide` MCP server; LSP plugins add value
  mainly for terminal/headless sessions.
- The official LSP plugins have had packaging regressions (an open marketplace
  issue reports installs shipping without their `.lsp.json`). If `/plugin
  install` succeeds but no diagnostics appear, check `/plugin` and the plugin's
  issue tracker before debugging the project.

Codex: LSP plugins are Claude Code only. Codex has no equivalent hook; skip
this step there.

## Languages — official plugins

| Language | Binary (install first) | Plugin |
|---|---|---|
| Python | `npm i -g pyright` (or `pip install pyright`) | `pyright-lsp` |
| TypeScript / JavaScript | `npm i -g typescript-language-server typescript` | `typescript-lsp` |
| Rust | `rustup component add rust-analyzer` | `rust-analyzer-lsp` |
| Go | `go install golang.org/x/tools/gopls@latest` | `gopls-lsp` |
| Java | JDK + Eclipse JDT LS (`brew install jdtls`, or download) | `jdtls-lsp` |
| Kotlin | Kotlin LSP binary (JetBrains) | `kotlin-lsp` |
| C# | `dotnet tool install -g csharp-ls` | `csharp-lsp` |
| C / C++ | `brew install llvm` or `apt install clangd` | `clangd-lsp` |
| PHP | `npm i -g intelephense` | `php-lsp` |
| Ruby | `gem install ruby-lsp` | `ruby-lsp` |
| Swift | Xcode / Swift toolchain (`sourcekit-lsp`) | `swift-lsp` |
| Lua | `brew install lua-language-server` | `lua-lsp` |

Also published by URL in the official marketplace (verify in `/plugin` before
offering): `terraform-lsp`, `postgres-lsp`, `node-lsp`, `python-lsp`
(Jedi-based alternative to pyright), `liquid-lsp`.

### Other languages (custom plugin pattern)

Install the server binary, then create a minimal plugin whose `.lsp.json` maps
`command` + `extensionToLanguage`. Required fields only; see the Claude Code
plugins reference for optional ones (`initializationOptions`, `diagnostics`,
`restartOnCrash`, …). Example for Zig:

```json
{
  "zig": {
    "command": "zls",
    "args": [],
    "extensionToLanguage": { ".zig": "zig" }
  }
}
```

## Beyond LSP — symbol-level tools for large codebases

**Serena** (`serena@claude-plugins-official`, MCP server by oraios) sits on top
of a language server and exposes symbol-level retrieval and editing (find
symbol, references, insert after symbol…) across 30+ languages, so the agent
navigates a big repo without reading whole files. Offer it only when the
codebase is large enough that the user themself relies on go-to-definition:
monorepos, reference-heavy refactors, multi-language repos. In a small service
or a greenfield project it is ~20 extra tools for nothing. Codex: works as an
MCP server.

Code-graph servers (`codebase-memory-mcp`, `code-graph-mcp`, JetBrains
Context) index the repo into a call/import graph and answer structural
questions cheaply. Promising, young, no adoption data yet — don't offer by
default; mention them if a project asks for impact analysis.
