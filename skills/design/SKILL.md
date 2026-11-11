---
name: design
model: opus
description: Write the technical design for an SDD change (sdd/changes/<feature>/design.md) - decisions, affected files, risks. Use when the user runs /sdd:design after the proposal is approved.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Design

Write the technical design for a change. Argument: the feature name; if omitted and exactly one non-archived change exists in `sdd/changes/`, use it — otherwise ask.

## Steps

1. **Load context.** Read `sdd/project.md`, the change's `proposal.md`, and any `sdd/specs/` files it lists as affected. If there is no proposal, stop and point to `/sdd:new`. Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> design` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled).
   - **Worktree** (shared rule 10): `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . resolve <feature>`. If it prints a path that is not the current directory, enter it with `EnterWorktree` (`path`) before reading anything else — that is where this feature's documents live. Nothing printed means the feature has no worktree; work here. Protocol: `${CLAUDE_PLUGIN_ROOT}/references/isolation.md`.
   - **Steering**: if `sdd/steering/` exists, read each doc's frontmatter and fully load those whose `phases` (if present) include `design` and whose `applies_to` (if present) matches the proposal's scope. `architecture.md` and `security.md` rules are binding here — a design that needs to break one must say so explicitly as an open question, never silently.
2. **Triviality check.** If the change needs no real design decisions (obvious approach, few files, no new dependencies or data changes), say so and recommend skipping straight to `/sdd:tasks` instead of producing a ceremonial document. Only continue if the user insists or the change warrants it.
3. **Investigate the code** the change touches: current structure, patterns to follow, integration points. Design must fit the existing codebase, not an idealized one.
4. **Write** `sdd/changes/<feature>/design.md` using `${CLAUDE_PLUGIN_ROOT}/templates/design-template.md` — but first apply shared rule 6 (never silently overwrite an existing document; if `design.md` already exists, show it and ask regenerate/amend/keep). Rules for the content:
   - Every decision states the chosen option **and why**, with rejected alternatives one line each.
   - Reference real files/modules with paths.
   - Cover every requirement in the proposal — if a requirement has no design implication, say so explicitly.
   - Surface **open questions** rather than silently deciding on things the user should weigh in on.
   - No code beyond short illustrative snippets or interface signatures.
   - If a visual would say it better (flows, state machines, component interactions), generate it with the `sdd:diagram` skill and reference it from the design doc. Ask for **SVG** — it lives in the repository next to the document, diffs in review and renders inline on GitHub — and **never read the rendered file back into the session** (shared rule 11: an image costs ~140k tokens of context to look at, and the design doc already says in words what the picture shows).
5. **Design review (fresh context).** Before the gate, have the design reviewed by someone who has *not* seen this session — you hold the context, so you cannot see what you assumed but never wrote down. Methodology (single source for both runtimes): `${CLAUDE_PLUGIN_ROOT}/references/design-review.md`.
   - Runs on whatever `design.md` stands at the gate — written, amended or kept (shared rule 6).
   - **Provider preflight (Claude Code only, before the launch):** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/provider_profile.py" check --aliases opus`. Exit 1 → do not launch; report the missing variable names (names only) and treat the review as unavailable. Under Codex skip it (`references/runtime-provider.md`).
   - **Claude:** one `Agent` call, foreground, `subagent_type: sdd:design-goldfish`, `model: opus`. The prompt carries only: the feature name, the absolute paths of `proposal.md`, `design.md` (and `BLOCKED.md` if present), and the absolute path of the methodology resolved from `${CLAUDE_PLUGIN_ROOT}/references/design-review.md`. Never summarize the conversation, your intent or your reasoning for it — that defeats the review.
   - **Codex:** spawn one native subagent with a fresh context and a **read-only sandbox** where the runtime offers one, instructed to read and follow the methodology file, with the same inputs.
   - **Write guard (both runtimes):** read-only is verified, not trusted to the prompt. Immediately before the launch record `git status --porcelain=v1 --untracked-files=all` and `git diff HEAD | git hash-object --stdin`; immediately after the reply, record both again. Any difference → the review is **unavailable** (whatever its verdict says), report the changed paths, and never keep or build on what the reviewer wrote — restore `design.md` from your own version before continuing.
   - **Findings:** fix each `high` in `design.md`, or turn it into an open question for the gate. Re-review at most **once** (one review + one re-review), only if you changed a decision, and always with a **new** launch — never resume the first reviewer, which has seen the earlier version. `medium`/`low` you adopt or answer in one line each.
   - **Unavailable:** if the runtime cannot spawn a fresh-context reviewer, or the reviewer's last line is not exactly `VERDICT: PASS` or `VERDICT: REVISE` (an explicit `VERDICT: UNAVAILABLE`, no verdict, an unknown token or a reply cut off all count as unavailable), say so in the gate summary and never describe the review as done.
   - Skipped only when step 2 found the change trivial.
6. **Metrics.** Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> design` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled).
7. **Gate.** Summarize the key decisions, the design review verdict with every finding left unresolved (or that it was unavailable), and open questions, resolve the open questions with the user (AskUserQuestion when they are concrete choices), and wait for approval. Then suggest `/sdd:tasks`.
