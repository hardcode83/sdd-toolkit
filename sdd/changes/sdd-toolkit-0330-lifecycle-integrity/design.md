# Design: SDD Toolkit 0.33 lifecycle integrity

## Context

Toolkit 0.33 stores lifecycle metadata in `sdd/changes/<feature>/STATE.md`.
`scripts/sdd_lifecycle.py:mark_ready()` captures `git rev-parse HEAD` and then
writes STATE, so the metadata becomes dirty after the reviewed commit. The ship
skill currently requires exact equality between HEAD and `implementation_sha`,
while the documented `record-pr` behavior claims to commit/push STATE although
the current `record_pr()` implementation only writes it. This change is a
Toolkit governance correction; AgentsLabs application code, P2, P3 and archives
are consumers/protected fixtures, not implementation targets.

## Decisions

### D1 — Stable implementation anchor, separate lifecycle commits

**Chosen:** `implementation_sha` remains the reviewed implementation commit and
is never rewritten to the SHA of a later lifecycle-only commit. A lifecycle
commit may follow it and may contain only lifecycle metadata. The lifecycle
commit does not store its own SHA inside `STATE.md`; Git history, HEAD and the
PR provide the external audit reference.

This avoids self-reference while preserving the exact implementation range
that review certified. Ship will verify that `implementation_sha` is an
ancestor of HEAD and that the post-anchor range is limited to the declared
lifecycle paths.

Rejected: requiring `HEAD == implementation_sha` after lifecycle persistence —
it makes a committed STATE containing the implementation SHA impossible without
rewriting history.

### D2 — `mark-ready` persists atomically as a lifecycle commit

**Chosen:** after validating tasks, blockers, approved review and base context,
`mark-ready` renders STATE with the implementation anchor captured before the
write, stages only the feature's `STATE.md`, and creates one deterministic
lifecycle commit when the file changed. The commit message identifies the
feature and lifecycle transition; it never amends, resets or rewrites history.
If STATE already matches the captured facts, the operation is idempotent.

Rejected: leave STATE dirty for ship — it conflicts with the clean handoff and
forces each caller to invent persistence behavior.

The precondition matrix is deterministic:

| Before transition | Result | Mutation |
|---|---|---|
| clean worktree | continue | one `STATE.md` lifecycle commit |
| unstaged non-STATE path | fail with non-zero exit | none |
| staged non-STATE path | fail with non-zero exit | none |
| pre-existing dirty `STATE.md` | fail with non-zero exit | none; never overwrite it |
| mixed dirty STATE and other paths | fail with non-zero exit | none |
| commit failure after helper staging | fail with non-zero exit | restore the helper's original STATE bytes and unstage only its path; never reset user paths |

The successful transition ends with a clean worktree and a commit whose parent
is the captured implementation/lifecycle HEAD.

### D3 — Ship verifies an anchored, lifecycle-only suffix

**Chosen:** replace exact HEAD equality with ancestor and per-commit checks:

1. `implementation_sha` exists and is an ancestor of HEAD.
2. Ship enumerates every commit in `implementation_sha..HEAD`, in order.
3. Every later commit must be classified as an authorized lifecycle commit and
   may modify only the feature's `STATE.md`.
4. Ship rejects any later commit that touches code, evidence, specs, metrics or
   another path outside the allowlist, even when the aggregate diff appears
   limited.

Ship still refuses code/evidence changes after review. A lifecycle-only suffix
is not a new implementation range. The worktree must be clean before push.

Rejected: accept any descendant HEAD — it would publish unreviewed code.

The classifier is machine-checkable and applies to every commit individually.
An authorized commit must:

- have exactly one parent;
- have the subject exactly equal to
  `chore(sdd): lifecycle <feature> <transition>` with no suffix or extra text,
  and have the trailer
  `SDD-Lifecycle-Feature: <feature>`;
- use a feature identifier that is one safe directory name with no `/`, `\\`,
  `..`, empty component or path-normalization ambiguity; resolve it relative to
  the Git root and compare exactly one normalized path
  `sdd/changes/<feature>/STATE.md`;
- modify exactly that normalized `sdd/changes/<feature>/STATE.md` path;
- parse both parent and child STATE documents successfully;
- use one allowed transition: `ACTIVE -> LOCAL_VERIFIED`,
  `LOCAL_VERIFIED -> READY_FOR_PR` or `READY_FOR_PR -> PR_OPEN`;
- require valid STATE.md in both parent and child commits;
- preserve the stable implementation anchor in every lifecycle commit. The
  `ACTIVE -> LOCAL_VERIFIED` child records its parent implementation commit;
  later lifecycle commits preserve that same value and never use their own SHA.

Any arbitrary commit that edits only STATE.md but lacks this topology, message,
trailer, safe feature identifier or valid transition is rejected. Path
traversal, alternate separators and equivalent normalized paths are rejected.
No aggregate diff-only shortcut is permitted.

### D4 — `record-pr` owns its documented persistence

**Chosen:** after validating the GitHub PR identity and state, `record_pr()`
writes the PR fields, stages only that feature's `STATE.md` and creates an
explicit PR-metadata commit. `record_pr()` does not push; push is exclusively
ship's responsibility. The skill documentation will describe that boundary
precisely and will not claim that `record-pr` publishes remotely.

Rejected: write STATE without commit — it recreates the dirty handoff and makes
PR evidence local-only.

### D5 — Review has an explicit lifecycle postcondition

**Chosen:** review panels evaluate the implementation range and protected scope;
after each official lifecycle transition, review checks that the worktree is
clean, `implementation_sha` remains the stable anchor, every later commit is
authorized lifecycle metadata, and `STATE.md` matches the transition. The
panel must not treat a legitimate lifecycle-only suffix as functional drift,
but must reject any unauthorized later commit.

Rejected: have QA inspect a pre-`mark-ready` dirty STATE as if it were an
uncommitted implementation.

Review's post-transition test matrix is: clean after `mark-ready`; clean after
`record-pr`; matching stable `implementation_sha` in STATE and Git ancestry;
every suffix commit classified; and failure on any dirty or mixed worktree.

### D6 — Test isolated Git repositories and command contracts

**Chosen:** add Toolkit tests using temporary Git repositories and controlled
fixtures. Tests will assert commit topology, exact changed paths, state fields,
exit codes and clean/dirty status rather than only matching prose. The suite
covers `mark-ready`, review's postcondition, ship's anchor/suffix gate,
`record-pr`, lifecycle-only commits and attempts to smuggle code after the
implementation anchor.

Rejected: test only against the AgentsLabs worktree — it would couple Toolkit
behavior to application history and miss the self-reference invariant.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Lifecycle implementation | `scripts/sdd_lifecycle.py` | Add atomic lifecycle commit helper; persist `ACTIVE -> LOCAL_VERIFIED` before `mark-ready`, update `mark-ready` and `record-pr`; expose stable anchor/suffix validation; preserve idempotence. |
| Ship gate | `scripts/sdd_lifecycle.py::validate_ship_suffix` and `skills/ship/SKILL.md` | Implement the effective ancestry, commit-by-commit classifier invocation and clean-worktree gate; the skill performs push only after the CLI gate passes. |
| Ship contract | `skills/ship/SKILL.md` | Replace exact-equality wording with ancestor + lifecycle-only suffix checks; document clean handoff and actual record/push boundary. |
| Review contract | `skills/review/SKILL.md` | Document post-`mark-ready` lifecycle commit and clean postcondition; distinguish lifecycle-only suffix from implementation drift. |
| Shared automation | `skills/auto/SKILL.md` | Align handoff/commit language with the official lifecycle operation. |
| Tests | `tests/test_sdd_lifecycle.py`, `tests/test_lifecycle_contract.py` | Cover all R4 cases with temporary repositories and failure cases. |
| Governance docs | `README.md`, `docs/guide.md` | Record the stable-anchor/lifecycle-commit model and audit rules in the versioned Toolkit documentation. |

## Data & interfaces

No AgentsLabs domain, persistence or runtime interface changes. The lifecycle
metadata schema keeps `implementation_sha` as the stable implementation anchor;
no `self_sha` or equivalent self-referential field is introduced. The helper
may accept an explicit feature path and commit message, but must stage only
allowlisted lifecycle paths and return the resulting external commit SHA for
logs/tests without embedding it in STATE.

The closed lifecycle allowlist contains only:

- `sdd/changes/<feature>/STATE.md`

Generic metrics are excluded. Another artifact may be added only by an explicit
future decision that defines it as deterministic Toolkit lifecycle metadata.

Usage metrics are a separate observability ledger, not lifecycle metadata. They
must not be staged, included in the suffix allowlist or used to make an
implementation commit appear lifecycle-only. If a metrics command dirties a
tracked path, the phase reports the dirty worktree and does not claim a clean
lifecycle handoff; the metrics operation must remain outside this transition.

## Risks & mitigations

- **Unreviewed code after the anchor:** reject any post-anchor path outside the
  lifecycle allowlist and test a malicious code commit.
- **Partial metadata commit:** stage exact paths and fail before commit if the
  index contains unrelated changes; test mixed dirty trees.
- **Forged lifecycle commit:** require the exact transition predicate, trailer,
  subject, parent topology and STATE semantic comparison; test a fake STATE-only
  commit that fails classification.
- **Duplicate lifecycle commits:** compare rendered STATE before committing and
  make repeated operations idempotent.
- **Documentation drift:** test the skill contract strings/fixtures and run
  Toolkit doctor plus the consumer's validation suite.
- **Remote timing:** keep push/PR ownership explicit; record-pr must not claim a
  remote push it did not execute.

The required regression cases are named and independently assert exit code,
HEAD/parent topology, paths and final status:

- `test_mark_ready_clean_commits_state_only`
- `test_mark_ready_rejects_unstaged_or_staged_unrelated_paths`
- `test_mark_ready_rejects_preexisting_state_edits_without_overwrite`
- `test_mark_ready_rolls_back_helper_stage_on_commit_failure`
- `test_review_post_transition_requires_clean_and_coherent_anchor`
- `test_ship_accepts_each_authorized_lifecycle_commit_after_anchor`
- `test_ship_pushes_only_after_all_lifecycle_gates_pass`
- `test_ship_rejects_code_commit_after_anchor`
- `test_ship_rejects_arbitrary_state_only_commit`
- `test_ship_rejects_subject_suffix_and_path_traversal`
- `test_ship_enumerates_all_post_anchor_commits`
- `test_record_pr_commits_state_without_invoking_push`
- `test_lifecycle_commit_does_not_embed_its_own_sha`
- `test_metrics_path_is_not_lifecycle_allowlisted`

## Open questions

None. The allowlist is only `STATE.md`; `record-pr` commits without pushing;
ship owns the push exclusively.
