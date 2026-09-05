---
name: ship
model: sonnet
effort: medium
context: fork
background: false
description: Publish a change that is READY_FOR_PR - sync the base into its branch, push it, open the Pull Request and record the PR evidence in STATE.md. Use when the user runs /sdd:ship, or accepts the offer at the end of /sdd:review.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Ship

Publish a locally verified change: **sync → push → Pull Request → recorded
evidence**. Argument: the feature name; if omitted and exactly one non-archived
change is at `READY_FOR_PR`, use it — otherwise end the turn with a `HANDOFF`
listing the candidates and the exact `/sdd:ship <feature>` per option (shared
rule 11: this phase runs forked and cannot ask).

This phase exists because gating archive on a proven merge (shared rule 8) opened
a stretch of the flow that nothing owned: `/sdd:review` stops at `READY_FOR_PR`
and `/sdd:archive` refuses to start before the merge. Only `/sdd:auto` crossed it,
so the manual path had to be driven by hand, one instruction at a time. Ship is
that stretch, and `/sdd:auto` runs this same skill — one home for the logic
(shared rule 1), not two copies that drift.

Integrating the base is part of that stretch. With several features in flight the
base moves under every open PR, so "this branch has conflicts" belonged to nobody
either: review had finished, archive refuses to start before the merge, and the
resolution happened by hand in between, unrecorded. Ship owns it — and only it:
ship never reviews, never merges the PR and never archives.

## Steps

1. **Worktree, then state.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . resolve <feature>` — if it prints a path that is not the current directory, work there for the rest of the phase — prefix every command with `cd <path> &&` (or `--root <path>` for the SDD scripts) and read files by absolute path, because `cd` does not persist between calls in a forked phase and `EnterWorktree` is not to be relied on there (shared rule 11): the branch to push is checked out there, not here. Nothing printed → continue here. Protocol: `${CLAUDE_PLUGIN_ROOT}/references/isolation.md`.

   Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> ship` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled). Without this mark, ship's spend is attributed to review.

   Then read `sdd/changes/<feature>/STATE.md` and act on its `state`:

   - `READY_FOR_PR` → this is the case ship is for; continue.
   - `PR_OPEN` → the PR already exists, but the base may have moved under it:
     run step 3, push if it changed anything, re-run `record-pr` with the
     recorded URL (idempotent, re-validates against GitHub), report the PR and
     stop. Skip steps 4 and 5. **Before this branch**, check whether the
     branch has unanchored commits: compare `HEAD` (from
     `git rev-parse HEAD`) to the recorded `implementation_sha`. If they
     differ, a functional commit landed on the open PR without recertification;
     abort with an actionable message — "execute `/sdd:review <feature>` to
     recertify the fix on the same PR" — and do NOT run step 3, do NOT
     re-run `record-pr`, do NOT push. Ship publishes; it does not certify.
   - `ACTIVE` or `LOCAL_VERIFIED` → not publishable yet: no reviewed `implementation_sha` means nothing objective to attach the PR to. Point to `/sdd:review <feature>` and stop.
   - `MERGED` → point to `/sdd:archive <feature>` and stop.
   - A `BLOCKED.md` with a `decision` entry (or one whose type cannot be read — `sdd_lifecycle.py blocked <feature>` lists them typed) → do not publish work that is waiting on a human decision. Show the entries and stop. `deferred` and `assumed` entries do **not** stop ship: they travel with the PR and are listed in its body (step 5).

   **Never ask for the base branch.** `mark-ready` recorded `base_branch`, `head_branch`, `repository` and `implementation_sha` in `STATE.md`; those are the facts, and asking again invites a different answer than the one the evidence was recorded against.

2. **Verify the anchored lifecycle suffix before publishing.** Run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . validate-ship <feature>
   ```

   This requires a clean worktree, proves `implementation_sha` exists and is an
   ancestor of `HEAD`, and validates every commit on the branch's first-parent
   line after that anchor. Exactly two shapes pass: a single-parent STATE-only
   lifecycle commit whose subject, trailer, transition and changed path match the
   feature's allowlist, and the **base-sync merge** step 3 records — two parents,
   its second one contained in the base, and STATE.md untouched. Code, specs,
   evidence, metrics, traversal aliases, arbitrary STATE-only commits and any
   other merge fail. A lifecycle suffix is accepted without changing the stable
   implementation anchor.

3. **Sync the base into the branch, before anyone judges the PR.** Run it on
   every ship; it is a no-op when the base has not moved:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . sync-base <feature>
   ```

   It fetches and **merges** `origin/<base>` into the branch, and never rebases:
   a rebase rewrites `implementation_sha` out of existence, and that anchor is
   the evidence rule 8's merge gate reads. A merge keeps it an ancestor of
   `HEAD`, which is exactly what step 2 asserts.

   Two exit codes matter:

   - **`0`** — nothing left to do: either the base was already contained, or the
     merge is committed as `chore(sdd): sync <feature> <base>@<sha>`. Continue.
   - **`2`** — the merge is **in progress** and the paths listed under `PENDING`
     need a decision. What it could decide it already did: the append-only
     bookkeeping (`sdd/roadmap.md`, `sdd/metrics.md`) is union-merged, and
     anything it refused to union is reported with why (a union that would
     duplicate an entry is not a resolution). Everything else is yours:

     1. **Resolve every pending path.** This is the one place ship edits content.
        Resolve for what the change *means*, not for what makes the conflict go
        away — the base's side is somebody else's shipped work, and dropping it
        silently is the worst available outcome.
     2. **Re-verify.** The resolution is code no review ever saw: the approval
        recorded against `implementation_sha` predates it. Run the project's own
        verification command (`sdd/project.md`, shared rule 9) and never invent
        one — a project that declares none is a finding, not a reason to guess.
     3. **Record it, whichever way it went:**

        ```bash
        python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . record-sync <feature> --verification '<command>'
        ```

        Add `--failed` when the verification did not pass; the commit itself then
        says so. `record-sync` refuses a resolution git still finds conflict
        markers in, and refuses a merge whose second parent is not contained in
        the base — relay either refusal verbatim.
     4. **Green** → continue to step 4. **Red, or no verification command
        exists** → stop here: write the BLOCKED entry (shared rule 5) naming the
        conflicted paths and the resume command `/sdd:review <feature>`, and do
        not open or update a PR with a resolution that does not build. The sync
        commit stays on the branch, unpushed, so nothing is lost.

   If the conflict reveals that the change itself is wrong rather than merely
   behind, `git merge --abort` is the way back — then `/sdd:run <feature>`.

4. **Require the claimed head branch to exist remotely.** PR creation needs a
   remote head. The branch-claim/bootstrap step in `/sdd:new` or `/sdd:auto`
   owns that initial publication; ship does not hide a bootstrap push. If
   `origin/<head_branch>` is absent, leave the change at `READY_FOR_PR` untouched and hand
   off the exact `git push -u origin <head_branch>` command. If it exists,
   continue; the only push performed by this ship flow is the final push in
   step 7, after `record-pr` has committed `PR_OPEN`.

5. **Open or validate the Pull Request** with `gh pr create`, base `base_branch`, head `head_branch`:
   - Title: `SDD: <feature>`.
   - Body: the proposal's Why/What, the review verdict, and a link to the change directory. If step 3 resolved anything, say which paths and how it was verified — the reviewer is entitled to know the branch carries a resolution the local review never saw. Then a section **"Pending, travelling with this PR"** listing every `deferred` and `assumed` entry of `BLOCKED.md` (type, title, and for `assumed` the option taken and its D#): the PR is where a human performs the deferred checks and vetoes the assumptions, and `/sdd:archive` will not close until each is acknowledged.
   - **Attribution follows the project's settings**: only append the Claude Code attribution line if `includeCoAuthoredBy` is not disabled in the effective settings — never hardcode a signature against the user's configuration.
   - A PR already open for that head branch → don't create a second one; take its URL and continue to step 6.
   - No `gh`, or `gh` fails (no permission, protected branch) → handoff, step 7.

6. **Record the evidence.** With the URL returned by `gh`:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . record-pr <feature> --url <PR-URL>
   ```

   It re-queries `gh`, validates repository/base/head/implementation SHA against what was recorded, writes `PR_OPEN` in an explicit STATE-only lifecycle commit, and never pushes. Ship is the only phase that pushes a **feature branch** — `/sdd:archive` publishes the bookkeeping commit it makes on the **base** branch, through `publish-archive`, and the two never touch the same ref. Re-running is idempotent. **Never fabricate a URL** — the point of this step is that the PR is a fact, not a claim.

7. **Push the branch.** Run `git push origin <head_branch>` exactly
   once, after `record-pr` succeeds — `record-pr` never invokes push. This
   publishes the `PR_OPEN` STATE-only commit and, when step 3 made one, the sync
   merge with it. If the final push is refused, leave
   the local state at `PR_OPEN` and report the exact retry command. If the
   branch bootstrap, `gh`, or the final push is unavailable, hand off without
   fabricating evidence; do not run `/sdd:archive`.

8. **Metrics.** Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> ship` (unconditionally; it no-ops when tracking is off).

9. **Close.** Report the PR URL (or the pending manual action), and — when step 3
   did anything — what the sync brought in, which paths were resolved and how the
   resolution was verified. Then state plainly that what remains is **not**
   ship's: the remote review, the merge, and then `/sdd:archive <feature>`. Never
   call a PR-open change shipped, merged or archived.

## Under `/sdd:auto`

Auto invokes this skill for its publish step, with the gate conversions its own
skill defines: no questions, handoffs never abort the run, and the run continues
with the next feature afterwards.

Step 3 keeps its judgement there, it does not lose it. Auto resolves the pending
paths and re-verifies exactly as above; a **red** verification or a project with
no verification command is a BLOCKED entry and the feature stops at
`READY_FOR_PR` with its sync commit unpushed — never a PR opened on a resolution
that does not build. That is the same rule auto applies to every other gate it
cannot pass on evidence.
