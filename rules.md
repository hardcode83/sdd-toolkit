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
5. **Phases**: `/sdd-toolkit:init` → `/sdd-toolkit:new` → `/sdd-toolkit:design` (optional if trivial)
   → `/sdd-toolkit:tasks` → `/sdd-toolkit:run` → `/sdd-toolkit:archive`, plus `/sdd-toolkit:status`
   (read-only) and `/sdd-toolkit:review` (drift / pre-archive check).
