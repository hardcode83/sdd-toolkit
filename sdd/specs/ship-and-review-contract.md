# Review / ship / auto contract on `PR_OPEN`

## Purpose

`/sdd:review`, `/sdd:ship` and `/sdd:auto` are the three skills that touch a
change while its PR is open. Without a shared contract, each could write to
`STATE.md.implementation_sha` or invoke a lifecycle command outside the
certification or publication it actually owns; the recertify flow this change
adds is precisely the contract that prevents that.

## Requirements

### `/sdd:review` branches on `STATE.md.state`

- WHEN `/sdd:review <feature>` is invoked with `state: ACTIVE` or `LOCAL_VERIFIED`, THE SYSTEM SHALL run the standard two-milestone sequence on PASS (`mark-local-verified`, `mark-ready <f> --base <base>`, `validate-ship`).
- WHEN `/sdd:review <feature>` is invoked with `state: PR_OPEN`, THE SYSTEM SHALL launch the review panel over the range `implementation_sha..HEAD` (the new functional fix only, not the whole branch) and, on PASS, call `mark-recertified` instead of the standard sequence. The post-fix `validate-ship` is still run to confirm the recertify commit is the only suffix commit.
- IF the panel reports FAIL a second round in a row, THE SYSTEM SHALL stop and hand the change to the user ("two fix rounds, then stop").
- WHEN `state: PR_OPEN`, THE SYSTEM SHALL require the user to have already `git push origin <head_branch>` (never `--force`/`--force-with-lease`) before invoking review, so that `mark-recertified`'s `gh pr view` HEAD-in-commits check passes.
- WHEN `state: PR_OPEN` and `HEAD == implementation_sha`, THE SYSTEM SHALL treat the change as already certified at HEAD — `mark-recertified` is a no-op.

### `/sdd:ship` refuses to recertify

- WHEN `/sdd:ship <feature>` is invoked with `state: PR_OPEN` and `HEAD != implementation_sha`, THE SYSTEM SHALL abort with an actionable message: "execute `/sdd:review <feature>` to recertify the fix on the same PR". The skill SHALL NOT run `sync-base`, SHALL NOT re-run `record-pr`, and SHALL NOT push.
- WHEN `/sdd:ship <feature>` is invoked with `state: PR_OPEN` and `HEAD == implementation_sha`, THE SYSTEM SHALL proceed with the existing flow: optional `sync-base` (no-op when the base has not moved), push if the sync produced new commits, and idempotent `record-pr` re-validation.
- WHEN `/sdd:ship <feature>` is invoked with `state: READY_FOR_PR`, THE SYSTEM SHALL run the standard publish path.
- IF the change is `ACTIVE` or `LOCAL_VERIFIED`, THEN THE SYSTEM SHALL refuse and point at `/sdd:review`.
- IF the change is `MERGED`, THEN THE SYSTEM SHALL refuse and point at `/sdd:archive`.
- IF `BLOCKED.md` is non-empty, THEN THE SYSTEM SHALL refuse and show the unresolved entries.

Ship publishes; it does not certify. The functional contract of `mark-recertified` is to record the review verdict and re-anchor the merge gate; that contract belongs to `/sdd:review`, never to ship.

### `/sdd:auto` delegates to `/sdd:review` on recertification

- WHEN `/sdd:auto <feature>` resumes a change with `state: PR_OPEN` and `HEAD != implementation_sha`, THE SYSTEM SHALL delegate to `/sdd:review <feature>` in a fresh delegated session. Auto itself SHALL NOT call `mark-recertified` directly — auto never certifies.
- WHEN `/sdd:auto <feature>` resumes a change with `state: PR_OPEN` and `HEAD == implementation_sha`, THE SYSTEM SHALL report the PR URL and wait; no auto logic runs.
- WHEN `/sdd:auto <feature>` resumes a change with `state: READY_FOR_PR`, THE SYSTEM SHALL run the ship skill.
- WHEN `/sdd:auto <feature>` resumes a change with `state: MERGED`, THE SYSTEM SHALL point at `/sdd:archive`.

### Pushing is a user action post-`PR_OPEN`

- WHEN a functional fix is committed on the open PR's branch, THE SYSTEM SHALL require the user to push it (`git push origin <head_branch>`, never `--force`) before invoking `/sdd:review`. `/sdd:review` SHALL NOT push, and `mark-recertified` SHALL NOT push.
- IF the user invokes `/sdd:review` on `PR_OPEN` without pushing the fix, THEN THE SYSTEM SHALL refuse (`mark-recertified`'s `HEAD ∉ commits[]` guard) and instruct the push.

The only push the lifecycle flow makes on a feature branch is the one `/sdd:ship` performs for the initial PR publication, which it does after `record-pr`. Once `state: PR_OPEN`, every push is the user's.

### What `/sdd:ship` does not change

- THE SYSTEM SHALL NOT modify `record-pr`, `mark-ready`, `sync-base`, `commit_sync`, `require_merge`, `validate_ship_suffix`, `classify_lifecycle_commit` (other than the recertify branch), `publish_archive`, or `mark-recertified` itself from inside the ship skill.
- IF a future change needs to touch those, THEN it shall do so via its own proposal / design / tasks lifecycle — not via an additive edit in `/sdd:ship`.

## Key files

- `skills/review/SKILL.md` — step 5 (the state-branched verdict) and the post-`PR_OPEN` "invalidates the recorded implementation_sha" note.
- `skills/ship/SKILL.md` — step 1 case `PR_OPEN` (the `HEAD != implementation_sha` → `/sdd:review` redirection) and the unchanged `HEAD == implementation_sha` branch.
- `skills/auto/SKILL.md` — "Resuming a mid-flight feature", the `PR_OPEN` rows.
- `tests/test_lifecycle_contract.py` — `test_review_skill_branches_at_pr_open_for_recertify` (C1), `test_ship_skill_refuses_pr_open_with_unanchored_head` (C2), `test_auto_skill_resumes_pr_open_with_recertify_path` (C3).