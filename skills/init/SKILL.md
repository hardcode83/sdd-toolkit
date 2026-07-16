---
name: init
model: sonnet
description: Bootstrap the SDD (Spec-Driven Development) workflow in this project - generates steering docs, optionally seeds from a planning document, creates a spec baseline for existing codebases, and interactively enables optional MCPs, LSPs and usage metrics. Use when the user runs /sdd:init or asks to set up SDD in a project.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Init

Bootstrap SDD in the current project. Optional argument: path to an initial planning document (markdown) — used to seed steering docs and the roadmap.

## Steps

### 1. Check existing state

- **Legacy layout**: if the project has pre-plugin SDD artifacts (`sdd/workflow/`, `.claude/skills/sdd-*`, `.opencode/command/sdd-*.md`), offer to delete them — the plugin replaces them and the data layer (`sdd/specs|changes|steering`, `project.md`, `roadmap.md`) is untouched. Also update any `<!-- sdd:start -->` block in CLAUDE.md to the current pointer text (step "Apply choices").
- If `sdd/project.md` exists and is already filled in (no placeholder comments), ask the user which parts to re-run: regenerate steering, re-run the extras step, add a spec baseline, or ingest a planning document. Skip everything else.

### 2. Analyze inputs

**The repository.** Explore the codebase to determine:

- What the project is (read README, package manifests).
- Stack: languages, frameworks, versions, infra (Dockerfiles, terraform, CI config).
- Components present: frontend, backend, infra, CLI, etc. — this drives which steering docs, MCPs and LSPs to offer.
- Exact commands for build, test, lint, and running locally (from package.json scripts, Makefile, justfile, CI workflows). Verify they exist; never invent commands.
- Conventions: folder structure, notable patterns, existing CLAUDE.md rules.

Keep exploration proportional — this is a steering summary, not an audit.

**The planning document** (if one was passed as argument). Read it and triage its content into three buckets, then confirm the triage with the user before writing anything:

| Content | Destination |
|---|---|
| Vision, target users, principles, goals | `sdd/steering/product.md` |
| Stack/architecture decisions already made | `sdd/project.md` + `sdd/steering/architecture.md` |
| Feature list / phases / milestones | `sdd/roadmap.md` — one line per future change, in order |

Do NOT turn the plan's features into proposals now — proposals are written just-in-time by `/sdd:new`, one at a time, when their turn comes.

**Re-ingesting an updated plan** (project already initialized): merge, never regenerate. Diff the plan against the current `sdd/roadmap.md` and steering, then:

- Checked (`[x]`) and in-progress (`→ changes/…`) entries are history — never rewrite or reorder them.
- New features → new `- [ ]` entries, inserted where they belong in the order.
- Dropped features → remove their pending entries (confirm first).
- Changed features not yet started → edit their pending line.
- Changes that contradict behavior already built (there's a spec in `sdd/specs/` for it) → don't just edit the roadmap: flag them explicitly as `/sdd:new` candidates, because reality now disagrees with the plan.
- Vision/architecture deltas → update the affected steering docs, showing the user the diff.

### 3. Write the core scaffold

Create if missing: `sdd/specs/`, `sdd/changes/archive/`, `sdd/README.md` (copy from `${CLAUDE_PLUGIN_ROOT}/templates/scaffold/sdd-readme.md`).

Write `sdd/project.md` with sections: **Overview**, **Stack**, **Commands** (exact, copy-pasteable), **Conventions**, **Context** (links, enabled MCPs/LSPs/metrics). Keep it under ~80 lines — it gets read at the start of every SDD phase.

If a planning doc provided a feature list, write `sdd/roadmap.md` from `${CLAUDE_PLUGIN_ROOT}/templates/roadmap-template.md`.

### 4. Steering docs

Read `${CLAUDE_PLUGIN_ROOT}/references/steering.md` for the format and loading rules. Ask the user (AskUserQuestion, multiSelect) which docs to create — tailor the component/language options to what step 2 detected:

- `product.md` — vision and principles. Seed from the planning doc if there is one; otherwise **interview the user briefly** (2-3 questions: what are we building, for whom, non-negotiable principles) — the vision is the one thing not derivable from code.
- `architecture.md` — architecture rules and standing decisions.
- `security.md` — security requirements and checklists.
- `testing.md` — test types and when, conventions, quality bars. Seed from the test setup actually present (frameworks, fixtures, CI gates).
- `documentation.md` — which docs must stay updated per change (API spec, runbooks, ADRs). Only what `sdd/specs/` doesn't already cover.
- Per-component docs (`frontend.md`, `backend.md`, `infra.md`, …) and/or per-language docs (`python.md`, `typescript.md`, …) — generate from the conventions actually observed in that part of the codebase.

Create the chosen ones in `sdd/steering/` from `${CLAUDE_PLUGIN_ROOT}/templates/steering/`, filling them with real content (repo analysis, planning doc, interview) — never leave placeholder-only files. Give each a correct frontmatter (`applies_to`, `phases`) per the reference doc.

Also offer: nested `CLAUDE.md` files per component directory for short always-on rules that apply even outside the SDD flow. If accepted, keep them to ~10 lines each and don't duplicate steering content — link to the steering doc instead.

### 5. Spec baseline (existing codebases)

If step 2 found significant existing functionality and `sdd/specs/` is empty, offer a baseline:

1. Propose the list of capabilities detected in the code (e.g. auth, billing, report-export).
2. Let the user pick the 3-6 **core** ones (AskUserQuestion, multiSelect). Recommend against a full backfill — speculative specs nobody audits are worse than no specs.
3. For each chosen capability, read the actual implementation and write `sdd/specs/<capability>.md` describing **current real behavior** (present tense, EARS), using `${CLAUDE_PLUGIN_ROOT}/templates/spec-template.md`.

Tell the user the rest is covered lazily: when a change touches an undocumented area, `/sdd:archive` creates its spec ("spec on first touch").

### 6. Offer optional extras

When re-running this step on an already-initialized project, first diff against what's already enabled (the **Context** section of `sdd/project.md` plus the actual config files) and offer only what's new or missing. Ask the user (AskUserQuestion) about:

1. **MCPs** (multiSelect) — read `${CLAUDE_PLUGIN_ROOT}/references/mcp-catalog.md`; offer only the entries relevant to the detected stack (e.g. don't offer Postgres to a project with no database).
2. **LSPs** (multiSelect) — read `${CLAUDE_PLUGIN_ROOT}/references/lsp-catalog.md`; offer code intelligence for the languages detected in the repo (or planned in the stack).
3. **CLAUDE.md pointer** — whether to add the SDD block (below) to the project's `CLAUDE.md`.
4. **Usage metrics** — per-feature token/cost tracking from conception to archive (see `${CLAUDE_PLUGIN_ROOT}/references/metrics.md`, including its honest limitations). Requires `jq` and `python3`.
5. **rtk (token savings)** — only if `which rtk` finds nothing. The plugin already ships a PreToolUse hook that rewrites Bash commands through [rtk](https://www.rtk-ai.app) (60-90% token savings on dev operations) and silently no-ops when the binary is absent — so the only thing to set up is the binary itself: offer to install it (`brew install rtk-ai/tap/rtk`, or `cargo install rtk`). If rtk is already installed, skip this item entirely (the hook is already working). If the user's global `~/.claude/settings.json` also wires an rtk hook, mention the duplication is harmless (the second rewrite is a no-op) but they can remove the global one.

### 7. Apply choices

- **MCPs**: merge the chosen entries into the project's `.mcp.json`. If the file exists, preserve every existing server — only add new keys. Mention any auth step the catalog notes.
- **LSPs**: per the catalog — check each chosen language server binary (`which`), install missing ones with user approval, then print the exact `/plugin install <name>` command(s) for the user to run (the agent cannot run slash commands itself).
- **CLAUDE.md pointer**: append the block below to the project's `CLAUDE.md` (create the file if missing). Idempotent — if the markers already exist, replace the block content instead of duplicating:

```markdown
<!-- sdd:start -->
## Spec-Driven Development

This project uses the SDD workflow (sdd plugin). Read `sdd/project.md` before significant work.
New features and non-trivial changes go through /sdd:new → /sdd:design → /sdd:tasks → /sdd:run → /sdd:archive.
Current system behavior is documented in `sdd/specs/`; in-flight changes live in `sdd/changes/`; standing rules in `sdd/steering/`.
<!-- sdd:end -->
```

- **rtk**: if chosen, install the binary with user approval and verify with `rtk --version`.
- **Usage metrics**: verify `jq` and `python3` are available. Merge into the `env` object of the project's `.claude/settings.json` (preserving existing keys): `CLAUDE_CODE_ENABLE_TELEMETRY: "1"`, `OTEL_METRICS_EXPORTER: "otlp"`, `OTEL_EXPORTER_OTLP_PROTOCOL: "http/json"`, `OTEL_EXPORTER_OTLP_ENDPOINT: "http://127.0.0.1:4318"` (pick another port if 4318 is taken — check with `lsof -i :4318`), `OTEL_METRIC_EXPORT_INTERVAL: "10000"`. Add `.sdd-usage/` to `.gitignore`. Tell the user telemetry starts on the **next session** (env applies at session start); the sink autostarts when the first phase runs.
- Record enabled MCPs/LSPs/metrics in the **Context** section of `sdd/project.md`.

### 8. Summarize

Report what was created/enabled. Note the per-phase model profile is fixed in the plugin (opus for new/design, sonnet for the bulk, haiku for archive/status) and is changed by editing the plugin's skill frontmatter, not per project. Suggest the first step: `/sdd:new` on the first roadmap entry if a roadmap exists, otherwise `/sdd:new <feature>`.
