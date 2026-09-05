---
name: init
model: sonnet
description: Bootstrap the SDD (Spec-Driven Development) workflow in this project - generates steering docs, optionally seeds from a planning document, creates a spec baseline for existing codebases, and interactively enables optional MCPs, LSPs and usage metrics. Use when the user runs /sdd:init or asks to set up SDD in a project.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Init

The repository being initialized is the consumer project, not the toolkit
checkout. Never copy the toolkit's tests, CI workflows, validation scripts,
Python configuration, or internal fixtures into it. Only the selected project
templates and generated SDD documents belong in the consumer repository.

Bootstrap SDD in the current project. Optional argument: path to an initial planning document (markdown) — used to seed steering docs and the roadmap.

## Steps

### 1. Check existing state

- **Legacy layout**: if the project has pre-plugin SDD artifacts (`sdd/workflow/`, `.claude/skills/sdd-*`, `.opencode/command/sdd-*.md`), offer to delete them — the plugin replaces them and the data layer (`sdd/specs|changes|steering`, `project.md`, `roadmap.md`) is untouched. Also update any `<!-- sdd:start -->` block in CLAUDE.md to the current pointer text (step "Apply choices").
- If `sdd/project.md` exists and is already filled in (no placeholder comments), ask the user which parts to re-run, then skip everything else. The menu is: regenerate steering, re-run the extras step, add a spec baseline, ingest a planning document, **shrink or restructure the roadmap** (step 3's migration), or revisit worktree isolation (step 3b). The last two are the ones an initialized project silently never gets, so offer them on evidence rather than always:
  - **Roadmap**: whenever `sdd-doctor.py --root .` reports `SDD025` (the index outgrew its budget), or `sdd/roadmap.md` has entries but no `## Stage` heading, or `sdd/roadmap/` does not exist while entries carry their rationale inline. Note which of the three you saw — they are different jobs (size, grouping, per-entry notes) and the user may want only one.
  - **Isolation**: whenever `sdd_session.py --root . policy` reports the default and nothing is declared — projects initialized before the policy existed have no line at all, and the question was never put to them.

  Both of these live in later steps that a re-run skips by design; without this they are unreachable on exactly the projects that need them.

### 2. Analyze inputs

**The repository.** Explore the codebase to determine:

- What the project is (read README, package manifests).
- Stack: languages, frameworks, versions, infra (Dockerfiles, terraform, CI config).
- Components present: frontend, backend, infra, CLI, etc. — this drives which steering docs, MCPs and LSPs to offer.
- Exact commands for build, test, lint, typecheck, and running locally (from package.json scripts, Makefile, justfile, CI workflows, or equivalent project configuration). Verify they exist; never invent commands or infer them from the plugin's implementation language. If no stack or command is identifiable, leave it pending and ask.
- Conventions: folder structure, notable patterns, existing CLAUDE.md rules.

Keep exploration proportional — this is a steering summary, not an audit.

**The planning document** (if one was passed as argument). Read it and triage its content into three buckets, then confirm the triage with the user before writing anything:

| Content | Destination |
|---|---|
| Vision, target users, principles, goals | `sdd/steering/product.md` |
| Stack/architecture decisions already made | `sdd/project.md` + `sdd/steering/architecture.md` |
| Feature list / phases / milestones | `sdd/roadmap.md` — an index: one line per future change, grouped into `## Stage N — <outcome>`, each with its metadata sub-line |
| A feature's long rationale / analysis | `sdd/roadmap/<feature>.md` — a note read only by that entry's `/sdd:new` |

Do NOT turn the plan's features into proposals now — proposals are written just-in-time by `/sdd:new`, one at a time, when their turn comes.

**Re-ingesting an updated plan** (project already initialized): merge, never regenerate. Diff the plan against the current `sdd/roadmap.md` and steering, then:

- Checked (`[x]`) entries and any entry with a `sdd/changes/<feature>/` directory are history or in flight — never rewrite or reorder them. (In-flight state is *not* marked in the roadmap; check the changes directory, not the entry text.)
- New features → new `- [ ]` entries in the stage they belong to, each with its metadata sub-line. Declare the relations the plan implies (`needs`, `completes`, `informs-from`, `inherits-from`) — that is what makes the order calculable instead of positional.
- Dropped features → remove their pending entries (confirm first), and remove or repoint any `needs:` that named them; a dangling dependency is an error `/sdd:doctor` will report (`SDD019`).
- Changed features not yet started → edit their pending line and its metadata.
- Changes that contradict behavior already built (there's a spec in `sdd/specs/` for it) → don't just edit the roadmap: flag them explicitly as `/sdd:new` candidates, because reality now disagrees with the plan.
- Vision/architecture deltas → update the affected steering docs, showing the user the diff.

### 3. Write the core scaffold

Create if missing: `sdd/specs/`, `sdd/changes/archive/`, `sdd/README.md` (copy from `${CLAUDE_PLUGIN_ROOT}/templates/scaffold/sdd-readme.md`).

Write `sdd/project.md` with sections: **Overview**, **Stack**, **Commands** (exact, copy-pasteable), **Conventions**, **Context** (links, enabled MCPs/LSPs/metrics). Keep it under ~80 lines — it gets read at the start of every SDD phase.

If a planning doc provided a feature list, write `sdd/roadmap.md` from `${CLAUDE_PLUGIN_ROOT}/templates/roadmap-template.md`. Three rules for filling it:

- **Stages are outcomes, not categories.** `## Stage 2 — reservas reales entrando por webhook`, never `## Backend`. Grouping by category hides the dependency chains, because chains cross categories. Category labels (`[FE]`, `[BE]`…) belong inline on the entry, if the project wants them.
- **Declare only the relations the plan actually states.** Inventing dependencies is worse than leaving the graph flat: an entry with no metadata is simply always workable, which is correct when nothing is known. Do not guess `needs:`.
- **Keep the index short.** One scannable line per entry. If the plan carries pages of rationale for a feature, that goes to `sdd/roadmap/<feature>.md`, not into the entry — `sdd/roadmap.md` is read by every phase, so its size is a cost paid on every run.

Then verify what you wrote: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_roadmap.py" --root . validate` must report no errors, and `… report` should show a frontier that matches the plan's intended starting point.

**Migrating an existing flat roadmap** (re-init over a project that predates stages): offer it, never do it silently, and show the diff. Group the **pending** entries into stages, transcribe into metadata the relations their prose already states ("depende de X", "cierra el cuarto ítem de Y", "hereda de Z"), and move the long analysis to `sdd/roadmap/<feature>.md`. A flat roadmap keeps working unmigrated: with no declared relations every open entry is in the frontier, which is exactly the old behaviour.

**If the file is oversized** (`/sdd:doctor` reports `SDD025`), that half is a mechanical pass with its own procedure and its own proof: `${CLAUDE_PLUGIN_ROOT}/references/roadmap-migration.md`. Do it **separately** from the two judgement calls above — it is verifiable (no text lost, graph unchanged, doctor clean) in a way that inventing stages and dependencies is not, and mixing them makes the whole diff unreviewable. Note that it relocates the analysis of **closed** entries too: their line in the index is not the historical record — that lives in `sdd/changes/archive/<date>-<feature>/` and in the living spec — so moving the text verbatim keeps rule 8 intact while a rewrite would not.

### 3b. Worktree isolation (shared rule 10)

Three things the project has to own, because the plugin cannot guess any of them (protocol: `${CLAUDE_PLUGIN_ROOT}/references/isolation.md`) — a worktree's whole life, from when it is created to when it is decommissioned:

1. **Choose when features get isolated.** Ask (AskUserQuestion) and write the answer as a one-line `isolation:` declaration in the **Worktree bootstrap** section of `sdd/project.md`. Two values, and the trade-off is real in both directions — present it, don't recommend blindly:

   - `on-conflict` **(default; recommended for solo work on a heavy stack)** — a worktree only when the check finds evidence: another live session, HEAD on another feature's branch, other in-flight changes. Nothing changes for a project that declares nothing.
   - `always` **(recommended when several sessions run at once, or when the main clone must stay usable)** — every feature gets its own worktree, the first one included. The main clone stays on the default branch with a clean tree, so every session starts from the same world. Without it the *first* feature occupies the clone and leaves it pinned to its branch, dirty — which is both a nuisance for any other shell and the exact evidence the next feature's check reports as a conflict.

   **Say the price before they choose**, from what step 2 detected: every feature then pays the worktree bootstrap — an empty database, a dependency reinstall, its own disk — that the first feature used to dodge. And if this project has an **exclusive resource** (item 3), `always` hits it on the first feature instead of the second: either write the operational rule now or stay on `on-conflict` until it exists.

   A project that skips the question gets `on-conflict`; that is the default, not a gap. A value that is neither is an error (`SDD026`), because it would silently fall back.
2. **Ignore the worktree directory.** Add `.claude/worktrees/` to `.gitignore` if it isn't there. Not optional: committing it nests a checkout inside the repo, and every later `git status` and file search sees a duplicate of the whole tree. `/sdd:doctor` reports it missing — and under `isolation: always` it reports it *before* the directory exists, since the next `/sdd:new` creates one.
3. **Declare the bootstrap — all three parts of it.** Write a **Worktree bootstrap** section in `sdd/project.md` covering three different things:

   - **What is missing**: what a fresh worktree does not carry (`.env`, `.venv`, `node_modules`, a local database) and the exact command to get it. Without this the project's own verification fails there and the failure looks like a code problem.
   - **What cannot exist twice**: *exclusive resources*. A published port, a fixed container name, a daemon on a known socket, a database with a fixed name, a lockfile. **A project can need nothing copied and still be unable to run two dev stacks** — the symptom is `address already in use`, or a suite that passes alone and fails while a sibling worktree is up. This half gets forgotten precisely because it is not a missing file.
   - **How it comes down again**: a one-line `teardown:` declaration, the command `/sdd:archive` runs *inside* a worktree before retiring it (`teardown: docker compose down --volumes --remove-orphans`, `teardown: make down`). Only the project knows whether `--volumes` destroys seed data somebody needs, so the toolkit asks and never guesses — and a project that brings a stack up per worktree and declares no teardown gets its retirement **refused** later, with the inventory of what it owns and the exact line to declare, derived from what docker reported. Answering it here is cheaper than answering it while archiving. Leave it empty only if nothing is brought up per worktree.

   Ask the user (AskUserQuestion) rather than guessing, and seed the options from what you can see: gitignored files at the repo root (`.env*`, `*.local`), a lockfile implying an install step, a `Makefile` target like `setup`/`bootstrap`, and — for the second and third parts — **published ports in a compose file**, fixed `container_name`, a hardcoded database name, anything binding a known socket, plus the `down`/`clean`/`stop` targets that already exist in the `Makefile` or `package.json`. Record only what they confirm.

   If the project genuinely needs nothing and has no exclusive resource, write the section saying exactly that: an explicit "nothing to copy, nothing exclusive" is worth more than a missing section, because the next phase then knows the answer instead of asking again.

   **Name the cost of getting the teardown wrong**, because it is invisible until it bites: compose isolates volumes per directory, so each worktree has its own set — and a `down` without `--volumes` leaves them with no project label, which means nothing can ever attribute them to the worktree that created them again. Measured on one machine: 56 dangling volumes, 5.1 GB, no owner. On macOS those same mountpoints carry the `deny delete` ACL that makes the worktree directory undeletable.

   When there **is** an exclusivity constraint, write the operational rule it implies ("one stack at a time: `make down` there before `make up` here") — and say that fixing it properly is a roadmap entry with a design phase, not a note here: it touches the compose file, the task runner and possibly CI. The three questions that decide the shape of that fix are in `${CLAUDE_PLUGIN_ROOT}/references/isolation.md`; do not pick per-worktree ports reflexively, since the tests often need no published ports at all.

### 4. Steering docs

Read `${CLAUDE_PLUGIN_ROOT}/references/steering.md` for the format and loading rules. Ask the user (AskUserQuestion, multiSelect) which docs to create — tailor the component/language options to what step 2 detected:

- `product.md` — vision and principles. Seed from the planning doc if there is one; otherwise **interview the user briefly** (2-3 questions: what are we building, for whom, non-negotiable principles) — the vision is the one thing not derivable from code.
- `architecture.md` — architecture rules and standing decisions.
- `security.md` — security requirements and checklists.
- `testing.md` — test types and when, conventions, quality bars. Seed from the test setup actually present (frameworks, fixtures, CI gates).
- `documentation.md` — which docs must stay updated per change (API spec, runbooks, ADRs). Only what `sdd/specs/` doesn't already cover.
- Per-component docs (`frontend.md`, `backend.md`, `infra.md`, …) and/or per-language docs (`python.md`, `typescript.md`, …) — generate from the conventions actually observed in that part of the codebase.

Create the chosen ones in `sdd/steering/` from `${CLAUDE_PLUGIN_ROOT}/templates/steering/`, filling them with real content (repo analysis, planning doc, interview) — never leave placeholder-only files. Give each a correct frontmatter (`applies_to`, `phases`) per the reference doc.

**Project reviewers for the panel.** The review panel's core (architect/security/qa) already enforces `architecture.md`/component docs, `security.md`, and `testing.md` + EARS. For each steering lens **not covered by a core reviewer** — whether just created or detected in the plan/codebase (performance, i18n, tenancy, accessibility, compliance…) — offer to create its project reviewer:

- Only offer lenses whose rules are concrete enough to verify (a reviewer without a sharp referent is noise — the finding contract will discard everything).
- If accepted: create the steering doc if it doesn't exist yet (real content, as above) AND `.claude/agents/sdd-review-<lens>.md` from `${CLAUDE_PLUGIN_ROOT}/templates/reviewer-template.md`, filling referents/checks/model from the project's reality. Both files are versioned with the repo — the team gets the reviewer on clone.
- Remind that `/sdd:run` and `/sdd:review` will discover it automatically by the filename convention.

Also offer: nested `CLAUDE.md` files per component directory for short always-on rules that apply even outside the SDD flow. If accepted, keep them to ~10 lines each and don't duplicate steering content — link to the steering doc instead.

### 5. Spec baseline (existing codebases)

If step 2 found significant existing functionality and `sdd/specs/` is empty, offer a baseline:

1. Propose the list of capabilities detected in the code (e.g. auth, billing, report-export).
2. Let the user pick the 3-6 **core** ones (AskUserQuestion, multiSelect). Recommend against a full backfill — speculative specs nobody audits are worse than no specs.
3. For each chosen capability, read the actual implementation and write `sdd/specs/<capability>.md` describing **current real behavior** (present tense, EARS), using `${CLAUDE_PLUGIN_ROOT}/templates/spec-template.md`.

Tell the user the rest is covered lazily: when a change touches an undocumented area, `/sdd:archive` creates its spec ("spec on first touch").

### 6. Offer optional extras

When re-running this step on an already-initialized project, first diff against what's already enabled (the **Context** section of `sdd/project.md` plus the actual config files) and offer only what's new or missing. If `sdd-doctor.py --root .` reports `SDD029`, the project's `.mcp.json` still carries a server that no longer works (an endpoint switched off upstream, a package archived) — offer the catalog's current replacement for that entry before anything new. Ask the user (AskUserQuestion) about:

1. **MCPs** (multiSelect) — read `${CLAUDE_PLUGIN_ROOT}/references/mcp-catalog.md`; offer only the entries relevant to the detected stack (e.g. don't offer Postgres to a project with no database).
2. **LSPs** (multiSelect) — read `${CLAUDE_PLUGIN_ROOT}/references/lsp-catalog.md`; offer code intelligence for the languages detected in the repo (or planned in the stack).
3. **CLAUDE.md pointer** — whether to add the SDD block (below) to the project's `CLAUDE.md`.
4. **Usage metrics** — optional plugin-side per-feature token/cost tracking from conception to archive (see `${CLAUDE_PLUGIN_ROOT}/references/metrics.md`, including its honest limitations). Its helper runtime may use `jq` and Python 3 on the machine; this does not define the consumer project's stack or validation commands.
5. **Team distribution** (shared repos): declare the plugin in the project's versioned `.claude/settings.json` so whoever clones and trusts the folder gets the install prompt automatically. THREE keys, and each one earns its place — `enabledPlugins` alone says "you need this" without saying where to get it, and the first two together still leave everyone frozen on whatever version they installed:

   ```json
   "extraKnownMarketplaces": {
     "sdd-toolkit": {
       "source": { "source": "github", "repo": "hardcode83/sdd-toolkit" },
       "autoUpdate": true
     }
   },
   "enabledPlugins": { "sdd@sdd-toolkit": true }
   ```

   **`autoUpdate` is not optional in a shared repo, and it is the one people get wrong.** It defaults to `false` for every marketplace that is not an official Anthropic one, so without it a teammate stays on the version they first installed *forever* — no prompt, no notice. Measured on a real install: three days and two releases behind, silently. With it, startup refreshes the marketplace **and** the installed plugin in one operation (verified end to end), so a release reaches the team on their next session.

   Say this to the user when you write it: everyone on the team ends up on the same version automatically, and the flow's own guarantees (shared rules, doctor codes, lifecycle gates) only hold if they are all running the same one. Two people on different versions is how a `STATE.md` written by one becomes unreadable to the other.

   The opt-out exists and is worth naming: settings load user → project → local, so anyone who wants manual control sets `"autoUpdate": false` in their gitignored `.claude/settings.local.json` without touching the team's file.

   (Adjust repo if installing from a fork.) Merge into existing settings, never clobber.

   **Re-running on an already-initialized project**: if `extraKnownMarketplaces` is there but `autoUpdate` is missing, offer to add just that field — it is the single most common gap, since it did not exist when earlier projects were initialized.
6. **Official plugins** (multiSelect) — read `${CLAUDE_PLUGIN_ROOT}/references/plugin-catalog.md`; offer the entries relevant to the detected stack/team, watching the overlap rules it documents (LSPs live in their own catalog; integrations must not be offered both as plugin and raw MCP). You cannot install plugins yourself — print the exact `/plugin install <name>@claude-plugins-official` commands for the user, and point them to the `/plugin` Discover tab as the browsable catalog.

### 7. Apply choices

- **MCPs**: merge the chosen entries into the project's `.mcp.json`. If the file exists, preserve every existing server — only add new keys. Mention any auth step the catalog notes.
  **Offer only what this project needs.** Every enabled MCP server, plugin and agent adds its tool schemas and instructions to the static preamble of *every* request in the project — measured at a median of 42k tokens before a session does anything, on 19k requests. A server that belongs to another of the user's projects is pure overhead here; say so when the global config carries ones this stack has no use for, and point at per-project `.mcp.json` and `.claude/settings.json` as where that gets scoped (shared rule 11).
- **LSPs**: per the catalog — check each chosen language server binary (`which`), install missing ones with user approval, then print the exact `/plugin install <name>` command(s) for the user to run (the agent cannot run slash commands itself).
- **CLAUDE.md pointer**: append the block below to the project's `CLAUDE.md` (create the file if missing). Idempotent — if the markers already exist, replace the block content instead of duplicating:

```markdown
<!-- sdd:start -->
## Spec-Driven Development

This project uses the SDD workflow (sdd plugin). Read `sdd/project.md` before significant work.
New features and non-trivial changes go through /sdd:new → /sdd:design → /sdd:tasks → /sdd:run → /sdd:review → PR → merge → /sdd:archive.
Current system behavior is documented in `sdd/specs/`; in-flight changes live in `sdd/changes/`; standing rules in `sdd/steering/`.
<!-- sdd:end -->
```

- **Usage metrics**: if selected, verify the plugin's helper prerequisites (`jq` and Python 3) on the machine. Merge its environment into the project's `.claude/settings.json` (preserving existing keys): `CLAUDE_CODE_ENABLE_TELEMETRY: "1"`, `OTEL_METRICS_EXPORTER: "otlp"`, `OTEL_EXPORTER_OTLP_PROTOCOL: "http/json"`, `OTEL_EXPORTER_OTLP_ENDPOINT: "http://127.0.0.1:4318"` (pick another port if 4318 is taken — check with `lsof -i :4318`), `OTEL_METRIC_EXPORT_INTERVAL: "10000"`. Add `.sdd-usage/` to `.gitignore`. Tell the user telemetry starts on the **next session** (env applies at session start); the sink autostarts when the first phase runs. This optional helper is plugin infrastructure, not a project test requirement.
- Record enabled MCPs/LSPs/metrics in the **Context** section of `sdd/project.md`.

### 8. Summarize

Report what was created/enabled. Note the per-phase model profile is fixed in the plugin (opus for new/design, sonnet for the bulk, haiku for archive/status) and is changed by editing the plugin's skill frontmatter, not per project. Suggest the first step: if a roadmap exists, `/sdd:new` on the first entry of its frontier (`sdd_roadmap.py --root . frontier`) — and mention `/sdd:status` as the way to see what is workable in parallel, the waves and the critical path. Otherwise `/sdd:new <feature>`.
