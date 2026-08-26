# Implementation anchor (`STATE.md.implementation_sha`)

## Purpose

`implementation_sha` is the reviewed commit every later merge gate reads from.
It is the only field that ties a STATE-only lifecycle commit to the code the
panel actually certified, and the field that archive's merge gate (`require_merge`,
`verify_local_merge`) verifies against the base branch. These rules are what
keep that anchor trustworthy: which transitions may write it, which may not, and
what catches manual edits.

## Requirements

### Which transitions may write `implementation_sha`

- WHEN `mark_local_verified` runs on the first `ACTIVE → LOCAL_VERIFIED` step, THE SYSTEM SHALL set `implementation_sha = HEAD` — that is the moment the local panel certifies the work.
- WHEN `mark_ready` runs on `LOCAL_VERIFIED → READY_FOR_PR`, THE SYSTEM SHALL preserve the existing `implementation_sha` (the stable anchor across ship preparation).
- WHEN `mark_recertified` runs on `PR_OPEN → PR_OPEN`, THE SYSTEM SHALL set `implementation_sha = HEAD` — the parent of the recertify commit, never the commit's own SHA — and include the previous anchor in the body as `SDD-Prior-Implementation-SHA: <old>` for traceability.
- WHEN `record_pr` runs on `READY_FOR_PR → PR_OPEN` (or `READY_FOR_PR → MERGED`), THE SYSTEM SHALL preserve the existing `implementation_sha`.
- WHEN any other lifecycle transition runs, THE SYSTEM SHALL refuse to change `implementation_sha` (the final `elif` in `classify_lifecycle_commit`).

The set of transitions permitted to write `implementation_sha` is therefore: `LOCAL_VERIFIED` (capture), `PR_OPEN->PR_OPEN` (re-anchor). All others must preserve.

### The self-reference guard

- WHEN a lifecycle commit writes `STATE.md`, THE SYSTEM SHALL refuse the commit if its own SHA appears anywhere in the child `STATE.md` text — this is what stops `implementation_sha` from pointing at the commit that wrote it.
- IF a recertify commit tried to write `implementation_sha = <own sha>`, THEN THE SYSTEM SHALL refuse via the self-reference guard before reaching the recertify branch.
- IF a recertify commit writes `implementation_sha = <parent sha>` (the reviewed HEAD), THEN THE SYSTEM SHALL accept it.

### The "real change" guard on recertification

- WHEN `classify_lifecycle_commit` examines a `PR_OPEN->PR_OPEN` commit, THE SYSTEM SHALL additionally enforce that `parent_state.implementation_sha != parent` (the anchor actually moved).
- IF the parent's `implementation_sha` already equals the parent SHA (no functional change), THEN THE SYSTEM SHALL refuse with "Recertification requires a new implementation_sha anchor".

### How `validate_ship_suffix` walks the anchor

- WHEN `validate_ship_suffix` runs, THE SYSTEM SHALL first require `implementation_sha` to be set, to be a valid SHA, and to be an ancestor of `HEAD`. The worktree must also be clean.
- WHEN it walks the suffix `implementation_sha..HEAD --first-parent`, THE SYSTEM SHALL accept each commit as either a single-parent lifecycle commit (classified by `classify_lifecycle_commit`) or a two-parent sync merge (validated by `validate_sync_commit`). Every other shape fails, naming the offending commit.
- IF the suffix is empty (HEAD already at the anchor), THEN THE SYSTEM SHALL return `[]` and accept.

### How `require_merge` uses the anchor

- WHEN `require_merge` runs and the change has a recorded PR, THE SYSTEM SHALL require `implementation_sha ∈ commits[]` of `gh pr view` — this is what proves the reviewed commit actually landed in the PR.
- WHEN `require_merge` runs and there is no recorded PR (local-evidence path), THE SYSTEM SHALL either prove `implementation_sha` is an ancestor of the base (`ancestor`), or prove the base carries the same change under another SHA via `verify_equivalent_merge` (`equivalent`).
- IF neither holds, THEN THE SYSTEM SHALL refuse with a per-evidence-kind actionable message ("not contained in base', and no commit there carries the same change").

### Manual edits are not a path to a new anchor

- IF `STATE.md.implementation_sha` is edited by hand between two lifecycle commits, THEN THE SYSTEM SHALL refuse at the next `classify_lifecycle_commit` call: either the new transition is not in `LIFECYCLE_TRANSITIONS`, or `child.implementation_sha != parent.implementation_sha` for a transition that is not in {`LOCAL_VERIFIED`, `PR_OPEN->PR_OPEN`}.
- IF a commit claims subject `PR_OPEN->PR_OPEN` but `child.implementation_sha ≠ parent`, THEN THE SYSTEM SHALL refuse ("Recertification must record the reviewed HEAD as the new implementation_sha anchor").
- IF a commit claims subject `PR_OPEN->PR_OPEN` with `parent.implementation_sha == parent`, THEN THE SYSTEM SHALL refuse ("Recertification requires a new implementation_sha anchor; the parent STATE.md already points at the reviewed HEAD").

### Backwards compatibility

- THE SYSTEM SHALL NOT bump the schema number when only the transitions set or classifier branches change. STATE.md `schema: 1` remains valid for in-flight changes; STATE_FIELDS is unchanged.

## Key files

- `scripts/sdd_lifecycle.py` — `STATE_FIELDS`, `lifecycle_commit`, `classify_lifecycle_commit` (the four branches: `READY_FOR_PR` preserve, `LOCAL_VERIFIED` capture, `PR_OPEN->PR_OPEN` recertify, `elif` reject-all-others), `validate_ship_suffix`, `require_merge`, `verify_local_merge`, `verify_equivalent_merge`.
- `tests/test_sdd_lifecycle.py` — `LifecycleRecertifyTests` plus the pre-existing classifier / ship-suffix coverage that the change must not regress (the out-of-scope guard in `tasks.md` 4.4).