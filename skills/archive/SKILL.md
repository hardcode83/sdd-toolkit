---
name: archive
model: haiku
description: Archive a merged SDD change after objectively verifying its Pull Request, then update living specs, roadmap, metrics, and history. Use when the user runs /sdd:archive after the associated PR is merged.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Archive

Close out a merged change. Argument: the feature name; if omitted and exactly one non-archived change exists in `sdd/changes/`, use it — otherwise ask.

Write spec updates in the same language as the existing specs (or the user's language for new ones).

## Steps

0. **Run this in the main worktree, on the base branch, one change at a time**
   (shared rule 10). Archive mutates `sdd/specs/`, ticks `sdd/roadmap.md`,
   consolidates metrics and moves directories — shared state, so it is the
   serialization point of the whole flow. Being post-merge, the base branch is
   also where the merged content actually is.

   Check where you are: `git rev-parse --git-dir` returning a path under
   `.git/worktrees/` means this is a linked worktree. Leave it first
   (`EnterWorktree` with the main worktree's `path`, or `ExitWorktree` with
   `action: "keep"`) and re-run there. Never archive from inside the feature's own
   worktree: the directory being moved would be the one you are standing in.

1. **Verify objective merge evidence before any final-state write.** Run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . verify-merge <feature>
   ```

   The helper requires all tasks checked, no active `BLOCKED.md`, and local
   review approved. It then proves the merge through one of three objective
   paths, picked from the recorded state — never from anyone's claim:

   - **PR evidence** (`merge_evidence: pr`), when a PR is recorded: complete PR
     metadata, matching GitHub repository/base/head and reviewed implementation
     SHA, plus GitHub state `MERGED`, `mergedAt`, and merge commit SHA from
     `gh pr view`.
   - **Ancestry evidence** (`merge_evidence: ancestor`), when there is no PR:
     git proves the reviewed `implementation_sha` is contained in the base
     branch (`origin/<base>` when published, otherwise the local base).
   - **Equivalence evidence** (`merge_evidence: equivalent`), when there is no
     PR and the merge rewrote history: git proves a base commit introduces the
     same change as the reviewed one (patch identity, ignoring blob hashes and
     line numbers, as `git patch-id` does), covering squash and rebase merges
     where the reviewed SHA can never be an ancestor. `merge_sha` is that base
     commit. Only the newest 200 base commits since the branch point are
     scanned; a change merged further back must be archived through its PR.

   The last two are what let workflows without GitHub PRs — no remote,
   trunk-based, GitLab, manual or squashed merges — close the loop instead of
   stalling at `READY_FOR_PR`.

   STOP on every failure and return its actionable message verbatim. An open PR,
   closed-unmerged PR, unverifiable PR, mismatched branch/commit, work missing
   from the base branch, incomplete task, or blocker has no override.
   A legacy active change without `STATE.md` must be reviewed and associated
   with its real PR; never invent evidence. Historical archives are untouched.
2. **Start archive accounting.** Mark the phase for usage attribution:
   `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> archive`
   (run unconditionally; the script no-ops when tracking is off).
   - **Steering**: if `sdd/steering/` exists, load the docs whose `phases` include `archive` and whose `applies_to` matches this change (e.g. `documentation.md`) and apply their archive-time rules/checklists before closing.
3. **Update the living specs only now, after verified merge.** For each capability the change touched (see "Affected specs" in the proposal, plus anything discovered during implementation):
   - Create or update `sdd/specs/<capability>.md` following `${CLAUDE_PLUGIN_ROOT}/templates/spec-template.md`.
   - **Spec on first touch**: if the capability has no spec yet (common in projects that adopted SDD with existing code), create it covering the capability's full current behavior — the pre-existing parts this change interacted with plus what the change added — not just the delta. Don't document unrelated corners you didn't touch.
   - Specs describe the system **as it is now**, in present tense, with EARS requirements — merge the change's requirements into them, don't append a changelog.
   - Verify statements against the actual implementation, not just the proposal: the code is the source of truth for what was built.
4. **Metrics.** Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> archive` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled). Do **not** consolidate by hand: step 6 recomputes both the ledger and the summary row from the captured log. The per-phase ledger travels with the change into the archive.
5. **Finalize once.** After verifying the spec changes, run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . finalize-archive <feature> --specs-confirmed
   ```

   It re-verifies the same evidence as step 1 (GitHub for `pr`, git for
   `ancestor`/`equivalent`), records `ARCHIVED` with that evidence and its merge
   SHA, moves the change to the dated archive, ticks the roadmap entry and
   updates its pointer. It is idempotent and never modifies living specs. If it
   warns that no roadmap entry names the feature, the tick did **not** happen:
   report that verbatim and fix `sdd/roadmap.md` — never claim a closed loop the
   roadmap does not show.
6. **Consolidate metrics from the log, after the move.** Run it unconditionally
   (no-ops when tracking is off):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/usage-sync.py" --root . sync <feature>
   ```

   Running it *after* `finalize-archive` is what makes the numbers complete: it
   rebuilds every phase row from `.sdd-usage/otel.jsonl` — including phases whose
   gate never wrote one and the spend that arrived after it did — and upserts the
   consolidated row in `sdd/metrics.md` with the archive date. Report its
   WARNING lines verbatim: they mean a recorded row holds more than the log can
   account for, and it was deliberately kept.
7. **Retire the feature's worktree, if it had one.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . resolve <feature>`. If it prints a path, the merge is proven and that isolated copy has no further use — **offer** to retire it (AskUserQuestion, recommend yes):

   ```bash
   git worktree remove <path>
   git branch -d sdd/<feature>
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . release <feature>
   ```

   Use plain git, not `ExitWorktree` — that tool only touches worktrees created by `EnterWorktree` in the *same* session, and archive normally runs in another. Full protocol in `${CLAUDE_PLUGIN_ROOT}/references/isolation.md`. `git worktree remove` refuses a dirty tree: surface that refusal instead of forcing it, because uncommitted work there is work that never reached the merge. If the user declines removal, still run `release` only if they also want the binding dropped — otherwise leave both, and say `/sdd:doctor` will report the worktree as an orphan of an archived change.
8. **Summarize.** List the spec files created/updated, PR URL, merge SHA, and archive location. Suggest committing the post-merge specs + archive together, **staged with `git add -A sdd/`**: `finalize-archive` moves the change directory on the filesystem and stages that move for you, but the specs, roadmap and metrics it deliberately left unstaged are yours to add — and an explicit-path `git add` is how a deletion silently gets dropped.
9. **Verify the commit, not the working tree.** Once the archive is committed, run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd-doctor.py"` and report its output.
   Run it **after** the commit: a clean doctor on an uncommitted tree proves
   nothing about what landed, and that gap is exactly how an orphaned `STATE.md`
   reaches the base branch and resurfaces as four errors on somebody else's run.
   In the commit diff the change's files must appear as **renames into**
   `sdd/changes/archive/<date>-<feature>/`; a bare addition there, with no
   deletion at the active path, means only half the move was committed. Never
   report a closed loop from a pre-commit doctor run.
