# SDD — shared rules (read by every phase skill)

1. **State lives in `sdd/`, not in the session.** Specs, changes, steering,
   roadmap — everything needed to continue this project is in those markdown
   files. Keep them truthful: specs match code, checkboxes match verified
   reality. Never rely on conversation memory for state.
2. **Language**: write generated documents in the language the user
   communicates in.
3. **Phase gates**: end each phase by presenting a summary and waiting for
   explicit user approval. Never chain into the next phase automatically.
4. **Context loading**: read `sdd/project.md` at the start of every phase.
   Steering docs in `sdd/steering/` load selectively per
   `${CLAUDE_PLUGIN_ROOT}/references/steering.md`.
5. **No pending work lives only in the conversation.** If a phase ends
   leaving anything undone or undecided — an interrupted panel, a skipped
   verification, a parked task, a question for the user — it MUST persist it
   in `sdd/changes/<feature>/BLOCKED.md` before finishing, one entry per
   item: **phase** · **type** (`decision`: needs a human / `deferred`: the
   flow can resume it) · **what & why** · **exact resume command** (e.g.
   `/sdd:review <feature>`). `/sdd:status` surfaces this queue first;
   `/sdd:archive` refuses to close a change with unresolved entries unless
   the user explicitly overrides; resolving an entry deletes it (delete the
   file when empty).
6. **Never silently overwrite an existing phase document.** Before writing
   `proposal.md`, `design.md`, or `tasks.md`, check whether it already
   exists. If it does: show it and ask what the user wants —
   **regenerate** (rewrite from scratch, replacing it), **amend** (adjust
   it in place for what changed), or **keep** (treat it as already
   approved and move to the next phase). Default recommendation is
   *amend* if the user has new input, *keep* otherwise — never
   regenerate by default. This matters most for `tasks.md`: if any task
   is already checked `[x]`, regenerating destroys verified progress —
   call that out explicitly before letting the user pick regenerate.
7. **Phases**: `/sdd:init` → `/sdd:new` → `/sdd:design` (optional if trivial)
   → `/sdd:tasks` → `/sdd:run` → `/sdd:archive`. Support: `/sdd:status`
   (read-only, includes the BLOCKED queue), `/sdd:review` (drift /
   pre-archive check), `/sdd:history` (read-only queries over the archive),
   `/sdd:auto` (the whole cycle with automated gate substitutes), and
   `/sdd:diagram` (visuals for design docs).
