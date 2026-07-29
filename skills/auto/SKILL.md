---
name: auto
model: sonnet
description: Run SDD features through local implementation, review, READY_FOR_PR, and Pull Request creation without archiving before merge. Uses one branch+PR per feature and a BLOCKED queue for human decisions. Use when the user runs /sdd:auto, optionally with a count or feature name.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first. This skill **overrides rule 3
(phase gates)**: the user has pre-authorized execution by invoking auto —
gates are replaced by the automated substitutes below. Everything else
(documents stay truthful, language, steering loading) applies unchanged.

# SDD — Auto

Arguments: `N` (number of roadmap entries to process; default 1) or a
specific feature name. Only roadmap entries are eligible — auto NEVER
invents scope.

## Preconditions (check all; abort with a clear message if any fails)

1. Git repo with a **clean working tree**. Record the current branch as BASE.
2. `sdd/roadmap.md` exists with at least one unchecked, un-started entry
   (or the named feature is one).
3. `sdd/steering/` has at least `architecture.md` or `security.md` or
   `testing.md` — with no steering, the panel (the only reviewer in auto)
   has weak referents. Warn and require explicit user confirmation to
   proceed without them.

## The gate-conversion rule

Everywhere a phase skill says "ask the user" or "wait for approval", auto
substitutes:

- **Ambiguity that changes requirements** (new), **open questions** (design),
  **blockers**, **persistent panel findings** (run/review), or any
  DESIGN-CONFLICT that can't be resolved by making the documents match
  already-approved sources → **BLOCK the feature** (see contract below) and
  move on. Never guess to keep moving — guessing is exactly what gates
  prevent.
- **Approvals** → replaced by the automated checks listed per phase.

## Per-feature pipeline

Take the next unchecked, un-started roadmap entry. Then:

1. **Branch + claim**: check `git ls-remote --heads origin "sdd/<feature>"` — if it exists, the feature is claimed by someone else: skip it (report in the final summary) and take the next entry. Otherwise `git checkout -b sdd/<feature>` from BASE and, if a remote exists, **push the branch immediately** — publishing the claim before doing any work, not after.
2. **new** — follow `${CLAUDE_PLUGIN_ROOT}/skills/new/SKILL.md`. Approval
   substitute: the proposal must trace every requirement to the roadmap
   entry (and its source doc, if referenced) and respect `product.md`.
   Commit: `sdd(<feature>): proposal`.
3. **design** — follow the design skill (skip if trivial, as it says).
   Approval substitute: launch `sdd-architect` to review the **design
   document** against `architecture.md` and the proposal before any code.
   Any open question the design surfaces → BLOCK (no one can answer it).
   Commit: `sdd(<feature>): design`.
4. **tasks** — follow the tasks skill. Approval substitute: verify every R#
   is covered by at least one task (the skill already requires this — here
   it's a hard check). Commit: `sdd(<feature>): tasks`.
5. **run** — follow the run skill with the panel **mandatory** (`solo` mode
   is forbidden in auto; `tournament` only if the roadmap entry explicitly
   says so). Findings persisting after 2 fix rounds → BLOCK. Commit after
   each completed section: `sdd(<feature>): section <n>`.
6. **review + READY_FOR_PR** — follow the review skill at feature scale.
   Verdict must pass; otherwise BLOCK. The review skill records
   `LOCAL_VERIFIED` and then `READY_FOR_PR` in the change's single
   `STATE.md`, including BASE, head branch, repository, and reviewed
   implementation SHA. Commit: `sdd(<feature>): ready for PR`.
7. **Publish**: if a remote exists, push; if both a remote and `gh` are
   available, open a PR from `sdd/<feature>` to BASE — title
   `SDD: <feature>`, body = the proposal's
   Why/What + panel verdict + link to the **active** change. **Attribution
   follows the project's settings**: only append the Claude Code attribution
   line (and co-author trailers in commits) if `includeCoAuthoredBy` is not
   disabled in the effective settings — never hardcode signatures against
   the user's configuration.
8. **Record PR evidence**: take the URL returned by `gh pr create` and run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . record-pr <feature> --url <PR-URL>
   ```

   This re-queries `gh`, validates repository/base/head/implementation SHA,
   records `PR_OPEN`, then commits and pushes `STATE.md` once. Re-running is
   idempotent. No remote or no `gh` → leave `READY_FOR_PR` and report the
   exact manual action (open the PR, or merge into the base branch yourself);
   never fabricate a URL. Such a change is archived later through ancestry
   evidence once its commit is in the base.
9. **STOP before archive.** Do not call `/sdd:archive`, update living specs,
   check off the roadmap, consolidate archive metrics, or move the change.
   Those final effects are permitted only once the merge is objectively proven
   — a `MERGED` PR, or the reviewed commit contained in the base branch.
10. `git checkout BASE` and continue with the next entry.

## Resuming a mid-flight feature

`/sdd:auto <feature>` where `sdd/changes/<feature>/` already exists does NOT start over — it resumes from the change's current phase with the same gate substitutes:

- `BLOCKED.md` present → do not resume; tell the user the feature awaits their decision and stop.
- Only `proposal.md` → continue at design (the existing proposal counts as approved: the user drove it).
- `proposal.md` + `design.md` → continue at tasks.
- `tasks.md` with unchecked tasks → continue at run.
- All tasks checked, no lifecycle metadata → continue at review.
- `state: READY_FOR_PR` → push/open the PR and record it; do not re-review.
- `state: PR_OPEN` → report the PR and wait for remote review/merge.
- `state: MERGED` → point to `/sdd:archive <feature>`; auto does not archive.

Documents already written by the user's manual phases are treated as approved input — never regenerate them. If the change lives on an existing `sdd/<feature>` branch, switch to it instead of branching anew. This enables the hybrid the gates make expensive: the human drives the thinking phases, auto finishes the mechanical ones.

## The BLOCKED contract

When blocking a feature:

1. Write `sdd/changes/<feature>/BLOCKED.md` (entry format per shared rule 5:
   phase · type · what & why · exact resume command): the exact question(s)
   a human must answer or the findings that persisted, and what was tried.
   This file is the handoff — write it so the user can decide in one read.
2. Commit whatever is consistent (documents + code that passed its
   verification) on `sdd/<feature>` — never leave uncommitted work.
3. Annotate the roadmap entry with ` ⛔ blocked`.
4. Return to BASE and continue with the next entry (or finish if none).

Unblocking is human: the user answers in BLOCKED.md's terms, deletes the
file, and resumes with the normal phase skills on that branch.

## Final report (always, even if everything blocked)

- Per feature: **PR open** (link; archive pending merge) /
  **ready for PR** (exact next action) / **blocked** (phase + one-line reason)
  / **skipped**. Never call a PR-open change shipped or archived.
- Always state that living specs and the definitive roadmap tick remain
  pending until merge, and that the next command after merge is
  `/sdd:archive <feature>`.
- Cost per feature from `sdd/changes/<feature>/metrics.md` if tracking is on.
- Anything the run revealed about steering docs being too vague to enforce —
  that's the user's lever for making the next auto run better.
