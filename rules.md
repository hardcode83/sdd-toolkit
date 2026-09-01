# SDD — shared rules (read by every phase skill)

1. **State lives in `sdd/`, not in the session.** Specs, changes, steering,
   roadmap — everything needed to continue this project is in those markdown
   files. Keep them truthful: specs match code, checkboxes match verified
   reality. Never rely on conversation memory for state.
   And each fact has **one** home: never copy derived state into a second file.
   A change's progress lives in its `STATE.md` and `BLOCKED.md`, so no phase
   annotates `sdd/roadmap.md` to say a change started, is blocked, or is ready —
   `/sdd:status` derives all of that. Only `/sdd:archive` writes the roadmap, and
   only post-merge. Duplicating derived state into a shared file is what made
   parallel work conflict (`docs/adr/0001-roadmap-structure-and-concurrency.md`).
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
   `/sdd:archive` refuses to close a change with unresolved entries;
   resolving an entry deletes it (delete the file when empty).
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
   → `/sdd:tasks` → `/sdd:run` → `/sdd:review` → `/sdd:ship` (base sync + push +
   PR + recorded evidence) → merge → `/sdd:archive`. Review proves local readiness;
   ship publishes it; only objective merge
   evidence permits archive, living-spec updates, and the final roadmap tick.
   Support: `/sdd:status`
   (read-only, includes the BLOCKED queue), `/sdd:doctor` (read-only,
   deterministic state consistency checks), `/sdd:review` (drift /
   pre-archive check), `/sdd:history` (read-only queries over the archive),
   `/sdd:auto` (automated gate substitutes through PR creation, never
   pre-merge archive), and
   `/sdd:diagram` (visuals for design docs).
8. **Lifecycle truth**: a lifecycle-managed change has one
   `sdd/changes/<feature>/STATE.md`. Its current state is one of `ACTIVE`,
   `LOCAL_VERIFIED`, `READY_FOR_PR`, `PR_OPEN`, `MERGED`, `ARCHIVED`, or
   `CANCELLED`; a non-empty `BLOCKED.md` is the existing lateral blocked
   state. Never infer PR or merge state from conversation text. Record and
   verify it through `${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py`.
   Historical archives without `STATE.md` are legacy records: do not rewrite
   them and do not invent merge evidence. A merge is proven in one of three
   objective ways, recorded in `merge_evidence`: `pr` (GitHub reports the
   associated Pull Request MERGED), `ancestor` (git proves the reviewed commit
   is contained in the base branch) or `equivalent` (the base carries the same
   change under another SHA, because it was squashed or rebased in). The last
   two serve workflows without PRs. All three are facts; none is ever a claim.
9. **Project validation is project-owned**: build, test, lint, typecheck and CI
   commands come from the consumer project's `sdd/project.md`,
   `sdd/steering/` or existing configuration. Never infer them from the
   toolkit's implementation language, and never copy the toolkit's internal
   tests or CI into a consumer repository.
10. **One feature, one branch, one working directory.** Two sessions sharing a
    clone share its HEAD, so a second `git checkout -b sdd/<other>` drags the
    first one's uncommitted files onto the wrong branch — and `mark-ready` then
    records a `head_branch`/`implementation_sha` that does not describe the work,
    corrupting the very evidence rule 8 depends on. So:
    - Before creating or switching to a feature branch, ask
      `${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py --root . check --feature <f>`.
      Its verdict describes the clone (`CLEAR`/`CONFLICT`); its **last line** is
      the instruction (`ISOLATE`/`WORK HERE`), because the project decides what a
      `CLEAR` clone means: `isolation: always` in `sdd/project.md` gives every
      feature its own worktree, and the default `on-conflict` isolates only on
      evidence. Obey the last line and follow
      `${CLAUDE_PLUGIN_ROOT}/references/isolation.md` — it says when to offer it
      and when to just do it.
    - A feature's worktree is recorded once (`claim`) and every later phase finds
      it with `resolve` — never by guessing a path. The registry is machine-local
      state in the shared git directory; the **remote** `sdd/<feature>` branch is
      still the team's claim, and the two are different facts.
    - Never write code for a feature while HEAD is on another feature's branch.
      Verify the branch before the first edit, not after.
    - `/sdd:archive` runs **only in the main worktree, on the base branch, one
      change at a time**: it mutates `sdd/specs/`, ticks the roadmap and moves
      directories. Being post-merge, that was already true in practice. The
      retirement it offers is the exception: `retire` relocates itself to the main
      worktree, so a session standing in the worktree it has to remove closes the
      loop instead of handing it to somebody else.
11. **A phase does not inherit the previous phase's context.** Rule 1 already
    makes this safe: everything a phase needs is in `sdd/`, so starting with an
    empty context loses nothing — and a phase that *would* break without the
    conversation is a rule 1 violation, not a reason to keep it. It matters
    because cost follows position, not work: re-measured over 80 features of a
    real project (Sep 2026), the main conversation was 75% of all spend, `run`
    averaged 444k of context per request and 79% of its cost was re-reading
    that context, while the panel's subagents were 19%. The terminal phases are
    expensive only because they run last.
    - Interactive: `review`, `ship`, `archive`, `status` and `history` declare
      `context: fork` (with `background: false`) in their skill frontmatter, so
      Claude Code runs them in a **fresh subagent with no conversation
      history**, and their `model:`/`effort:` are honoured there — which they
      are not for a skill running inline. The gates of the phases that stay
      inline (`new`, `design`, `tasks`, `run`) still recommend `/clear`.
    - **A forked phase cannot ask.** No subagent has `AskUserQuestion`, and
      Codex has no equivalent either. So a forked phase never stops on a
      question: it finishes everything that needs no answer, persists what
      rule 5 requires, and ends its turn with a `HANDOFF` block — what it did,
      what must be decided (with a recommendation), and the **exact command per
      answer**. The calling conversation asks the user and runs that command.
      A fork that reaches a decision it cannot make and has no handoff to give
      is a bug in the skill, not a reason to guess.
    - **Working directory in a fork**: `cd` does not persist between Bash calls
      in a subagent and `EnterWorktree` is not to be relied on there. Resolve
      the feature's worktree once (`sdd_session.py … resolve`), then prefix
      every command with `cd <path> &&` or pass `--root <path>` to the SDD
      scripts, and read files by absolute path.
    - Unattended: `/sdd:auto` runs its terminal phases in a **fresh headless
      session** (`claude -p`), and reads what came back from `STATE.md`, not
      from the sub-session's prose — evidence over claims, as in rule 8.
    - Full measurement and the available mechanisms:
      `${CLAUDE_PLUGIN_ROOT}/references/context-budget.md`.
