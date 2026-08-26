# Lifecycle state machine

## Purpose

Drives every SDD change through an allowlisted set of states, from active work
through archived records. The state machine and its transitions are the only
authority on what a STATE-only lifecycle commit is permitted to encode, and
every later merge gate (ship, archive) reads its evidence from there.

## Requirements

### The state set is fixed

- WHEN a change is created, THE SYSTEM SHALL initialize `STATE.md` with `state: ACTIVE`, `local_review: PENDING`, and no other fields set.
- IF any other lifecycle field is set before its parent transition has run, THEN THE SYSTEM SHALL refuse (a `READY_FOR_PR` cannot carry an empty `implementation_sha`, a `PR_OPEN` cannot carry an empty `pr_url`, etc.).

The state set is: `ACTIVE`, `LOCAL_VERIFIED`, `READY_FOR_PR`, `PR_OPEN`, `MERGED`, `ARCHIVED`, `CANCELLED`. Only `ARCHIVED` and `CANCELLED` are terminal; the rest are forward-only by design.

### Transitions are an allowlist

- WHEN a lifecycle commit is classified (`classify_lifecycle_commit`), THE SYSTEM SHALL accept only the transitions enumerated in `LIFECYCLE_TRANSITIONS`.
- IF a commit's subject encodes a transition not in the set, THEN THE SYSTEM SHALL refuse with an "invalid lifecycle transition" error.

The current set, in order:

| From | To | Who performs it | What it records |
|---|---|---|---|
| (initial) | ACTIVE | `start <feature>` | nothing beyond `local_review: PENDING` |
| ACTIVE | LOCAL_VERIFIED | `mark-local-verified` | `implementation_sha = HEAD`, `local_review: APPROVED` |
| LOCAL_VERIFIED | READY_FOR_PR | `mark-ready <f> --base <base>` | `repository`, `base_branch`, `head_branch` |
| READY_FOR_PR | PR_OPEN | `record-pr <f> --url <url>` | `pr_number`, `pr_url`, `pr_state: OPEN` |
| READY_FOR_PR | MERGED | `record-pr` (PR was already MERGED on first sight) | `pr_state: MERGED`, `merge_evidence: pr`, `merge_sha` |
| **PR_OPEN** | **PR_OPEN** | **`mark-recertified <f>`** | **new `implementation_sha = parent SHA`, body carries `SDD-Prior-Implementation-SHA: <old>`** |
| (anywhere) | ARCHIVED | `finalize-archive <f> --specs-confirmed` | post-merge bookkeeping, moves directory |
| (anywhere) | CANCELLED | (out of scope of this change) | the feature is dropped |

### Each transition has explicit preconditions and rejections

- WHEN `mark-local-verified` runs from `ACTIVE` or `LOCAL_VERIFIED`, THE SYSTEM SHALL accept it and overwrite `implementation_sha = HEAD` on the first ACTIVE → LOCAL_VERIFIED step.
- IF the current state is `READY_FOR_PR`, `PR_OPEN`, or `MERGED`, THEN THE SYSTEM SHALL be a no-op returning "Local verification already recorded".
- IF the current state is `ARCHIVED` or `CANCELLED`, THEN THE SYSTEM SHALL refuse with "Cannot mark local verification from lifecycle state '<state>'".

- WHEN `mark-ready` runs from `LOCAL_VERIFIED`, THE SYSTEM SHALL accept it and capture `repository`, `base_branch`, `head_branch`, `implementation_sha`.
- IF `local_review != APPROVED`, THEN THE SYSTEM SHALL refuse.
- IF the current state is already `READY_FOR_PR`, `PR_OPEN`, or `MERGED`, THEN THE SYSTEM SHALL be a no-op returning "READY_FOR_PR already passed; lifecycle is <state>".

- WHEN `record-pr` runs from `READY_FOR_PR`, THE SYSTEM SHALL accept the URL, validate it against `gh pr view`, and write `pr_number`, `pr_url`, `pr_state`, and either `state: PR_OPEN` (when GitHub reports OPEN) or `state: MERGED` (when GitHub reports MERGED, with full merge evidence).
- IF the GitHub state is `CLOSED` without merge, THEN THE SYSTEM SHALL refuse.
- IF the change is already `PR_OPEN` or `MERGED`, THEN THE SYSTEM SHALL be idempotent (re-validates and returns the recorded state).

- WHEN `mark-recertified` runs from `PR_OPEN` with `HEAD != implementation_sha`, THE SYSTEM SHALL write one STATE-only commit with subject `chore(sdd): lifecycle <feature> PR_OPEN->PR_OPEN` and `implementation_sha = HEAD` (the parent SHA), and shall NOT push.
- IF the current state is anything other than `PR_OPEN`, THEN THE SYSTEM SHALL refuse with an actionable message naming the current state and the correct path to get there (`/sdd:review` and `/sdd:ship` first).
- IF the working tree has changes outside `sdd/changes/<feature>/STATE.md`, THEN THE SYSTEM SHALL refuse without modifying anything.
- IF `tasks.md` has unchecked tasks or `BLOCKED.md` is non-empty, THEN THE SYSTEM SHALL refuse (canonical gates).
- IF `git branch --show-current != data["head_branch"]`, THEN THE SYSTEM SHALL refuse.
- IF `gh pr view` reports `state: MERGED`, THEN THE SYSTEM SHALL refuse and point at `/sdd:archive`.
- IF `gh pr view` reports `state: CLOSED`, THEN THE SYSTEM SHALL refuse and suggest reopening or opening a new PR via `/sdd:ship`.
- IF `HEAD ∉ gh pr view.commits`, THEN THE SYSTEM SHALL refuse and instruct the user to `git push origin <head_branch>` first.
- IF `HEAD == implementation_sha`, THEN THE SYSTEM SHALL be a no-op returning "Recertification is current; nothing to do" (idempotency — R4.1).

### Lifecycle commits are STATE-only

- WHEN a lifecycle commit is written (`lifecycle_commit`), THE SYSTEM SHALL touch exactly one path: `sdd/changes/<feature>/STATE.md`.
- IF the working tree has any other change, THEN THE SYSTEM SHALL refuse without staging anything.
- IF `STATE.md` already has staged changes, THEN THE SYSTEM SHALL refuse (the helper never overwrites user-owned bytes).

- WHEN `classify_lifecycle_commit` validates a commit, THE SYSTEM SHALL check: single parent, subject matches `LIFECYCLE_SUBJECT_RE`, transition in `LIFECYCLE_TRANSITIONS`, body carries exactly one `SDD-Lifecycle-Feature: <feature>` trailer, paths modified are exactly `sdd/changes/<feature>/STATE.md`, parent STATE.md exists and parses, child STATE.md parses, the encoded `before` and `after` states match, and the commit's SHA does not self-reference inside the child STATE.md text.

### The self-loop `PR_OPEN → PR_OPEN` has its own dedicated branch

- WHEN the classifier encounters `transition == "PR_OPEN->PR_OPEN"`, THE SYSTEM SHALL additionally enforce: `child.implementation_sha == parent` (the new anchor is the reviewed HEAD, never the recertify commit's own SHA — guarded by the existing self-reference guard) and `parent.implementation_sha != parent` (a real re-anchor happened; recertifying with no functional change is a no-op caught earlier).
- IF the classifier accepts a `PR_OPEN->PR_OPEN` commit, THEN THE SYSTEM SHALL leave the other branches untouched: `READY_FOR_PR` still preserves the stable anchor, `LOCAL_VERIFIED` still captures `implementation_sha = parent`, and the final `elif` still rejects any other transition that touches `implementation_sha`.

### Only the base sync merge escapes the STATE-only rule

- WHEN `validate_ship_suffix` walks the suffix, THE SYSTEM SHALL accept two shapes and refuse everything else: a single-parent lifecycle commit (classified by `classify_lifecycle_commit`) or a two-parent commit classified as `sync-base` by `validate_sync_commit`.
- IF the suffix contains any other commit (functional code, arbitrary STATE-only edits, spec changes, evidence files), THEN THE SYSTEM SHALL refuse with a per-commit error.

## Key files

- `scripts/sdd_lifecycle.py` — `STATES`, `LIFECYCLE_TRANSITIONS`, `lifecycle_commit`, `classify_lifecycle_commit`, `validate_ship_suffix`, `mark_local_verified`, `mark_ready`, `record_pr`, `mark_recertified`.
- `tests/test_sdd_lifecycle.py` — `LifecycleRecertifyTests`, plus the pre-existing transition / classifier / ship-suffix coverage.
- `tests/test_lifecycle_contract.py` — contract tests pinning the skill files to the lifecycle rules.