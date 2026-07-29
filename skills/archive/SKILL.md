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

1. **Verify objective merge evidence before any final-state write.** Run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . verify-merge <feature>
   ```

   The helper requires all tasks checked, no active `BLOCKED.md`, and local
   review approved. It then proves the merge through one of two objective
   paths, picked from the recorded state — never from anyone's claim:

   - **PR evidence** (`merge_evidence: pr`), when a PR is recorded: complete PR
     metadata, matching GitHub repository/base/head and reviewed implementation
     SHA, plus GitHub state `MERGED`, `mergedAt`, and merge commit SHA from
     `gh pr view`.
   - **Ancestry evidence** (`merge_evidence: ancestor`), when there is no PR:
     git proves the reviewed `implementation_sha` is contained in the base
     branch (`origin/<base>` when published, otherwise the local base). This is
     what lets workflows without GitHub PRs — no remote, trunk-based, GitLab,
     manual merges — close the loop instead of stalling at `READY_FOR_PR`.

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
4. **Metrics.** Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/usage-phase.sh" <feature> archive` (run it unconditionally — the script itself no-ops when tracking is off; NEVER skip it based on your own assessment of whether metrics are enabled). Then, if the change has a `metrics.md`, sum its token and cost columns and append one summary row to `sdd/metrics.md` (create it with header `| feature | phases | tokens in | tokens out | tokens cache | cost USD (est) | started | archived |` if missing). The per-phase ledger travels with the change into the archive.
5. **Finalize once.** After verifying the spec changes, run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . finalize-archive <feature> --specs-confirmed
   ```

   It rechecks GitHub, records `ARCHIVED` with PR URL/number and merge SHA,
   moves the change to the dated archive, checks the roadmap entry, and
   updates its pointer. It is idempotent and never modifies living specs.
6. **Summarize.** List the spec files created/updated, PR URL, merge SHA, and archive location. Suggest committing the post-merge specs + archive together.
