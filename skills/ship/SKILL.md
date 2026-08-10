---
name: ship
model: sonnet
description: Publish a change that is READY_FOR_PR - push its branch, open the Pull Request and record the PR evidence in STATE.md. Use when the user runs /sdd:ship, or accepts the offer at the end of /sdd:review.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Ship

Publish a locally verified change: **push → Pull Request → recorded evidence**.
Argument: the feature name; if omitted and exactly one non-archived change is at
`READY_FOR_PR`, use it — otherwise ask.

This phase exists because gating archive on a proven merge (shared rule 8) opened
a stretch of the flow that nothing owned: `/sdd:review` stops at `READY_FOR_PR`
and `/sdd:archive` refuses to start before the merge. Only `/sdd:auto` crossed it,
so the manual path had to be driven by hand, one instruction at a time. Ship is
that stretch, and `/sdd:auto` runs this same skill — one home for the logic
(shared rule 1), not two copies that drift.

Ship publishes. It never reviews, never fixes, never merges and never archives.

## Steps

1. **Worktree, then state.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . resolve <feature>` — if it prints a path that is not the current directory, enter it with `EnterWorktree` (`path`): the branch to push is checked out there, not here. Nothing printed → continue here. Protocol: `${CLAUDE_PLUGIN_ROOT}/references/isolation.md`.

   Mark the phase for usage attribution: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-mark.sh" <feature> ship` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled). Without this mark, ship's spend is attributed to review.

   Then read `sdd/changes/<feature>/STATE.md` and act on its `state`:

   - `READY_FOR_PR` → this is the case ship is for; continue.
   - `PR_OPEN` → the PR already exists. Re-run `record-pr` with the recorded URL (it is idempotent and re-validates against GitHub), report the PR and stop.
   - `ACTIVE` or `LOCAL_VERIFIED` → not publishable yet: no reviewed `implementation_sha` means nothing objective to attach the PR to. Point to `/sdd:review <feature>` and stop.
   - `MERGED` → point to `/sdd:archive <feature>` and stop.
   - A non-empty `BLOCKED.md` → do not publish work that is waiting on a human decision. Show the entries and stop.

   **Never ask for the base branch.** `mark-ready` recorded `base_branch`, `head_branch`, `repository` and `implementation_sha` in `STATE.md`; those are the facts, and asking again invites a different answer than the one the evidence was recorded against.

2. **Verify the anchored lifecycle suffix before publishing.** Run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . validate-ship <feature>
   ```

   This requires a clean worktree, proves `implementation_sha` exists and is an
   ancestor of `HEAD`, enumerates every commit in `implementation_sha..HEAD`,
   and validates each commit individually. Only single-parent commits whose
   subject, trailer, transition and changed path match the feature's
   `sdd/changes/<feature>/STATE.md` allowlist pass. Code, specs, evidence,
   metrics, traversal aliases and arbitrary STATE-only commits fail. A
   lifecycle suffix is accepted without changing the stable implementation
   anchor.

3. **Push** `head_branch` to the remote. No remote configured → this is a handoff, not a failure: go to step 6.

4. **Open the Pull Request** with `gh pr create`, base `base_branch`, head `head_branch`:
   - Title: `SDD: <feature>`.
   - Body: the proposal's Why/What, the review verdict, and a link to the change directory.
   - **Attribution follows the project's settings**: only append the Claude Code attribution line if `includeCoAuthoredBy` is not disabled in the effective settings — never hardcode a signature against the user's configuration.
   - A PR already open for that head branch → don't create a second one; take its URL and continue to step 5.
   - No `gh`, or `gh` fails (no permission, protected branch) → handoff, step 6.

5. **Record the evidence.** With the URL returned by `gh`:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . record-pr <feature> --url <PR-URL>
   ```

   It re-queries `gh`, validates repository/base/head/implementation SHA against what was recorded, writes `PR_OPEN` in an explicit STATE-only lifecycle commit, and never pushes. Ship remains the only phase allowed to push. Re-running is idempotent. **Never fabricate a URL** — the point of this step is that the PR is a fact, not a claim.

6. **Handoff when the environment cannot publish** (no remote, no `gh`, push refused): leave the change at `READY_FOR_PR`, report the **exact command the user has to run**, and say that such a change is still archivable later through local git evidence — the reviewed commit contained in the base, or a base commit carrying the same change after a squash or rebase (shared rule 8). Under `/sdd:auto` this never aborts the run.

7. **Metrics.** Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> ship` (unconditionally; it no-ops when tracking is off).

8. **Close.** Report the PR URL (or the pending manual action) and state plainly that what remains is **not** ship's: the remote review, the merge, and then `/sdd:archive <feature>`. Never call a PR-open change shipped, merged or archived.

## Under `/sdd:auto`

Auto invokes this skill for its publish step, with the gate conversions its own
skill defines: no questions, handoffs never abort the run, and the run continues
with the next feature afterwards.
