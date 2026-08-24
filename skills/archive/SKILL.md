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

   **And in a fresh session** (shared rule 11). Archive reads the merged code and
   the change's documents from disk; it needs nothing the conversation holds. Run
   after a long day of `/sdd:run` it averaged 634k of context per request in the
   measured corpus — the most expensive phase in the flow, for pure bookkeeping.
   If this session already carries other work, say so and recommend `/clear`
   before continuing.

   Check where you are: `git rev-parse --git-dir` returning a path under
   `.git/worktrees/` means this is a linked worktree; `sdd_session.py --root .
   check` names the main one (`main_worktree` in its JSON). Prefer to leave first
   (`EnterWorktree` with the main worktree's `path`, or `ExitWorktree` with
   `action: "keep"`) and re-run there.

   What that rule is actually about is the **base branch**, not the directory:
   steps 3–6 write `sdd/specs/`, `sdd/roadmap.md` and `sdd/metrics.md`, and those
   writes belong on the base — from the feature's branch they would land in the
   change nobody is going to merge again. So if you cannot move (a session pinned
   to one workspace, per-feature Orca-style sessions), the question to answer is
   where the base branch is checked out and whether you are on it, and git allows
   exactly one worktree to hold it at a time. If you are not on it and cannot get
   to it, say so and stop before writing anything: half an archive on the wrong
   branch costs more than a re-run.

   What is **no longer** a reason to stop is standing in the worktree that has to
   be retired. Retirement relocates itself (step 7), so the feature's own session
   can close the loop instead of ending with an instruction for somebody else.

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
7. **Retire the worktrees whose work has shipped.** Ask what git knows, not what the registry knows — a worktree created by hand never registered, and asking the registry is why one survived archive indefinitely:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . worktrees
   ```

   Each line is marked `RETIRABLE` or `en uso` with its blockers. `RETIRABLE` means all of it is proven: the change is archived, the branch is contained in its base, the tree is clean, nothing is unpushed, and **no other live session is inside**. Note which ones are retirable and **carry the decision to the closing question in step 8** — do not spend a separate turn on it. Retiring is one command per worktree:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . retire <feature>
   ```

   A worktree owns more than files, and this decommissions all of it in one order
   — **runtime → git → disk**: it takes the project's declared `teardown:`
   (`sdd/project.md`) down *inside* the worktree, then removes the worktree,
   deletes its branch, releases the binding, drops the worktree's now-dead
   entries from Claude Code's plugin registry, and verifies the directory is
   actually gone, stripping the `deny delete` ACL that blocks it on macOS. Report
   its lines (`runtime` / `git` / `plugins` / `disk` / `branches`) as they come.

   **A listing where nothing is `RETIRABLE` is not automatically the answer.**
   Two of the reasons used to be dead ends and no longer are — read them as work
   to finish in this turn, not as findings to report:

   - **you are standing in it** is not a blocker any more. `retire` moves itself
     to the main worktree before touching git, because everything after the
     removal (`git branch -d`, the binding, the ACL strip, the plugin registry)
     runs from a directory that no longer exists otherwise. The listing says so
     on its own line, and the outcome's `disk:` line names where you were moved.
     **Do the retirement last** and, the moment it reports `disk: clean`, enter
     the main worktree (`EnterWorktree` with its `path`) before running anything
     else — including step 9. Your working directory is gone; a `git` or `python3`
     call from there fails with `Unable to read current working directory` and
     names neither the worktree nor the retirement.
   - **a stack nobody declared how to stop** now comes with the exact line to
     declare, derived from what docker reported (`declare it to unblock:
     teardown: …`). That line is the answer to the closing question in step 8,
     not a homework assignment for the user.

   Two of those lines need relaying, not just printing:

   - **`disk: clean`** is followed by the directory that no longer exists. Any
     shell still sitting in it now has a cwd that does not resolve, and the
     `getcwd`/`ENOENT` errors that follow name neither the worktree nor the
     retirement. If the user is in that shell, tell them to `cd` out.
   - **`branches:`** lists refs carrying the feature's name that retirement did
     *not* touch: the published `origin/sdd/<feature>`, plus evidence, restore or
     stray branches the change created. Each says `contained` or `NOT contained`.
     **Never delete them on your own** — whose branch it is, is not the toolkit's
     call (shared rule 9), and a remote ref may be somebody else's upstream.
     Relay the list and let the user decide; `NOT contained` means it still holds
     work that never reached the base.

   Two refusals are answers, not obstacles, and both must be relayed verbatim
   rather than worked around:

   - **"it still owns … and sdd/project.md declares no teardown"** — the worktree
     has containers or volumes and the project never said how to stop them. The
     refusal already carries the line to declare, derived from the compose project
     docker itself reported (`teardown: docker compose down --volumes
     --remove-orphans`, plus `--rmi local` when it also built images; a container
     with no compose project gets no suggestion, because nothing here knows what
     started it). Do not turn that into a separate turn: show the inventory and
     **carry the suggested line into the step 8 question**, which offers to record
     it in `sdd/project.md` and retire in the same answer. Whether `--volumes` may
     run at all is still the project's call (shared rule 9 — never guess it over
     somebody's database), which is why it is asked once and never assumed.
     `--teardown '<cmd>'` for one run and `--skip-teardown` (keep the resources on
     purpose) both exist; use them only if the user says so.
   - **"the declared teardown failed"** — nothing was deleted and the stack is
     still attributable. That is deliberate: after git removes the directory, the
     volumes are dangling and no command can tell whose they were.

   Exit code `1` means a **leftover survived** on disk. Say so plainly: it is
   recorded, `orphans` and `/sdd:doctor` will keep reporting it, and it is not a
   closed loop. Every other blocker names work that did not reach the merge, or a
   session that would break. Full protocol in
   `${CLAUDE_PLUGIN_ROOT}/references/isolation.md`.
8. **Summarize, then close in one question.** List the spec files created/updated, PR URL, merge SHA, and archive location. Then ask **once** (`AskUserQuestion`, both questions in the same call, recommending yes to both):

   1. **Commit the archive and publish it on `<base>`?** — and if yes, do both:
      stage with `git add -A sdd/`, commit, then

      ```bash
      python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . publish-archive <feature>
      ```

      `finalize-archive` moves the change directory on the filesystem and stages
      that move for you, but the specs, roadmap and metrics it deliberately left
      unstaged are yours to add — and an explicit-path `git add` is how a deletion
      silently gets dropped. Leaving a half-staged archive as an instruction for
      the user is how an orphaned `STATE.md` reaches the base branch.

      **Publishing is part of closing the loop, not an extra.** The archive commit
      is the only commit the flow makes directly on the base, so an unpushed one
      leaves the base diverged from origin forever: every later feature branches
      from `origin/<base>` (`EnterWorktree`'s `fresh` default), the check reports
      unpushed commits on every one of them, and any other clone still reads this
      change as active. `publish-archive` fetches and refuses if the commits it
      would push touch anything outside `sdd/`.

      **A base that moved on is integrated, not refused.** Two archives closing in
      parallel diverge from `origin/<base>` by construction — the archive commit is
      the only commit the flow makes there — and they collide on files that are
      append-only by design (ADR 0001). So `publish-archive` rebases the local
      archive commits onto `origin/<base>` and resolves `sdd/metrics.md` and
      `sdd/roadmap.md` by keeping both sides' rows; its message names what it
      resolved. Anything it cannot decide — a spec, a doc, code, or a union that
      would duplicate an entry — **restores the branch untouched and refuses**:
      relay that verbatim and integrate nothing by hand on the user's behalf. On
      a shared base a force-push is never the answer.

      It is idempotent, and a repository with no remote is told so rather than
      failed. If the push is refused because the base is protected, it prints the
      bookkeeping-branch fallback: hand that off, do not invent a workaround.
   2. **Retire the worktrees step 7 marked `RETIRABLE`?** — and if yes, run `retire` for each.

      When step 7 found a worktree whose only blocker was an **undeclared
      teardown**, this is the same question, with the line it derived already in
      it: "record `teardown: <command>` in `sdd/project.md` and retire?". A yes
      writes that line into the **Worktree bootstrap** section, commits it with the
      archive, and retires. That is the whole point of asking here: the answer
      arrives once, in the turn that needed it, instead of the user having to come
      back and ask for the cleanup a second time.

   Never pass `--force` on the user's behalf, and never retire a worktree the command refuses for any other reason. A decline on either question is an answer: leave everything as is, say what remains and that `/sdd:doctor` will keep reporting it.
9. **Verify the commit, not the working tree.** If a retirement in step 8 moved
   you out of the worktree you were standing in, enter the main worktree first —
   otherwise this step cannot run at all. Once the archive is committed, run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd-doctor.py"` and report its output.
   Run it **after** the commit: a clean doctor on an uncommitted tree proves
   nothing about what landed, and that gap is exactly how an orphaned `STATE.md`
   reaches the base branch and resurfaces as four errors on somebody else's run.
   In the commit diff the change's files must appear as **renames into**
   `sdd/changes/archive/<date>-<feature>/`; a bare addition there, with no
   deletion at the active path, means only half the move was committed. Never
   report a closed loop from a pre-commit doctor run.

   State the loop as three facts, each one checked: the archive is **committed**,
   it is **published** on `origin/<base>` (or explicitly local, when there is no
   remote), and the worktrees are **retired** — or which of them survived and why.
   Anything you could not verify is reported as not done, not as done.
