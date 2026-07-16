---
name: status
model: haiku
description: Show the state of SDD changes - active changes, phase, task progress, and the roadmap as a to-do view. Use when the user runs /sdd:status or asks where a change or the roadmap stands.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Status

Report the state of the SDD workflow. Read-only — change nothing.

## Steps

1. List non-archived directories in `sdd/changes/`. For each, determine:
   - **Phase**: which of `proposal.md` / `design.md` / `tasks.md` exist.
   - **Progress**: if `tasks.md` exists, count `- [x]` vs `- [ ]` (e.g. `grep -c '^\s*- \[x\]'`).
   - **Pending queue**: if `BLOCKED.md` exists, this change has unresolved entries — show these FIRST, each with its type (`decision`: needs the user / `deferred`: resumable — show its resume command) and one-line reason. This is the user's inbox: decisions to make and deferred work to pick up.
2. **In progress by others** (only if the repo has a git remote): `git ls-remote --heads origin "sdd/*"` — list remote SDD branches that don't correspond to a local active change, as "en curso por otros" (branch name; add author/date via `git log -1` on the fetched ref if cheap). This completes the picture: claims live as remote branches before they're merged.
3. Count capability specs in `sdd/specs/` and recent entries in `sdd/changes/archive/`.
4. If `sdd/roadmap.md` exists, render it as a to-do view preserving order — one line per entry with its state: `✔` done (checked off), `▶` in progress (annotated with `→ changes/<feature>/` and not yet archived, or claimed by a remote `sdd/*` branch), `·` pending. Keep each line to the feature name + a few words; mark which pending entry is next.
5. Present a compact table: change · phase · tasks done/total · suggested next command (`/sdd:design`, `/sdd:tasks`, `/sdd:run`, or `/sdd:archive`). Below it, the roadmap to-do view with a progress count (e.g. `2/13`).

If `sdd/` doesn't exist, say so and point to `/sdd:init`. If there are no active changes, say so and point to `/sdd:new` (suggesting the next roadmap entry if there is one).
