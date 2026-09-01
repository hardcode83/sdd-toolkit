---
name: tournament
model: sonnet
description: Parallel generation for ONE hard task of an SDD change - three isolated implementers with different angles, the review panel as judge, the winner applied. Use when the user runs /sdd:tournament <feature> <task>, or /sdd:run <feature> tournament <task>. Never the default.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Tournament

Parallel generation for **one** task where solution variance is real —
algorithms, state machines, tricky concurrency — never for CRUD. Cost is ~3×
that task; the rest of the change runs through `/sdd:run` normally. It runs
only when the user asked for it explicitly (or a roadmap entry says so under
`/sdd:auto`); nothing in the flow auto-triggers it.

Arguments: the feature name and the task address in its `tasks.md` (e.g.
`2.1`), or enough description to identify one unchecked task unambiguously. A
task that is already checked, or an address that names a whole section, is a
stop: say so and point to `/sdd:run`.

## Steps

1. **Load context** exactly as `/sdd:run` step 1 does (project, proposal,
   design, tasks and `## Implementation Notes`; worktree and branch guard of
   shared rule 10; usage mark `run` — the tournament is billed as run).
2. **Launch 3 general-purpose agents in parallel**, in one message, each with
   `isolation: worktree`, each implementing the same task from the same
   design. Give every one the full referents (task text, R# with EARS text, D#
   quoted, steering rules quoted, test commands, notes) and a different angle:
   *simplest-correct*, *performance-first*, *defensive*. Each returns the same
   compact report `/sdd:run` asks of an implementer — files, commands run with
   results, notes — plus the diff range of its worktree. `model: opus` for all
   three: variance is the point, and a tournament on a cheap model measures the
   model, not the solutions.
3. **Judge with the review panel.** Launch the panel (core reviewers plus the
   project's, one message) with the three diffs and the same referents, asking
   for a ranked verdict per candidate in the JSON envelope of
   `reviewer_plan.py` — one envelope per candidate, `scope_id` naming it.
   Synthesize: the winner is the candidate with no referent-backed finding, or
   the fewest and least severe ones.
4. **Apply the winner** to the change's working tree (cherry-pick or patch from
   its worktree), then graft any clearly better idea from the losers as a
   separate, small edit — never a merge of three implementations. Append what
   was learned to `## Implementation Notes`. Remove the three worktrees.
5. **Verify and mark.** Run the task's tests; only then mark it `[x]`. If the
   task closed its section, the section panel of `/sdd:run` step 3 applies as
   usual. Hand back to `/sdd:run` for the rest of the change.

Runtimes without isolated subagents (Codex today) do not support tournament;
say so and offer `/sdd:run <feature> <task>` instead.
