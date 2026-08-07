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
2. `sdd/roadmap.md` exists and its **frontier** is non-empty (or the named
   feature is in it):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_roadmap.py" --root . frontier
   ```

   The frontier is the set of entries whose declared dependencies are all
   closed — the only entries that can be built right now. Abort if it is empty
   while open entries remain: everything left is waiting on something, and
   `sdd_roadmap.py --root . report` says on what. A roadmap that declares no
   relations puts every open entry in the frontier, so this is also the
   pre-existing behaviour for flat roadmaps.
   Any `ERROR` from `sdd_roadmap.py --root . validate` (a cycle, a dependency on
   an entry that does not exist) aborts the run: auto must not pick an order out
   of a graph that is known to be wrong.
3. `sdd/steering/` has at least `architecture.md` or `security.md` or
   `testing.md`. With no steering, the panel (the only reviewer in auto) has
   weak referents: **do not ask for confirmation** — the user pre-authorized
   this run. Proceed and state the weakness prominently in the final report,
   as the first thing to fix before the next run.

## The gate-conversion rule

**Auto never asks the user anything.** Do not call `AskUserQuestion` while
running auto — not for a gate, not for an ambiguity, not for a missing
argument. A question that cannot be answered by the substitutes below is
recorded as a BLOCKED.md entry and the run continues with the next feature.
Everywhere a phase skill says "ask the user", "wait for approval", or
"stop and ask", auto substitutes:

- **Ambiguity that changes requirements** (new), **open questions** (design),
  **blockers** (run: its "stop and ask rather than guessing" becomes this),
  **persistent panel findings** (run/review), or any DESIGN-CONFLICT that
  can't be resolved by making the documents match already-approved sources →
  **BLOCK the feature** (see contract below) and move on. Never guess to keep
  moving — guessing is exactly what gates prevent.
- **Approvals** → replaced by the automated checks listed per phase.
- **Shared rule 6** (an existing `proposal.md` / `design.md` / `tasks.md`, whose
  question is regenerate/amend/keep) → always **keep**: a document already on
  disk is approved input. Never regenerate, never ask. Only if keeping it is
  impossible — it contradicts the roadmap entry auto is executing — BLOCK.
- **Missing arguments** (the phase skills ask when the feature is ambiguous) →
  never applies: auto always passes the feature name explicitly.
- **`/sdd:new`'s dependency gate** (its question when an entry's `needs` are
  still open) → never applies either, and must never be answered by guessing:
  auto only takes entries from the frontier, and precondition 2 already aborts a
  named feature that is not in it. If it somehow fires, BLOCK — auto overriding
  a declared dependency is exactly the guess gates exist to prevent.
- **Ad-hoc roadmap registration** (`/sdd:new`'s question for features outside
  the roadmap) → never applies either: auto only consumes roadmap entries and
  never invents scope.

## Per-feature pipeline

Take the next **un-started entry from the frontier**, in the order the frontier
lists it — never the next line in the file. Un-started means no
`sdd/changes/<feature>/` at all (a change sitting at `READY_FOR_PR`, `PR_OPEN`
or `MERGED` is started, and awaits merge/archive, not a fresh run).

Re-read the frontier before each feature: closing one opens the entries that
were waiting on it, so a run of `N` can legitimately reach features that were
not workable when it started. Deferred entries (`deferred-until`) are never in
the frontier and auto never picks them — their trigger is a human judgement.

### One session per feature

**A multi-feature run must not carry feature 1 into feature 4.** Measured over
38 sessions of a real project, the sessions that touched three or more features
burned 5.09 B of the 7.42 B total: every request while building the fourth
feature re-read the diffs, tests and panel reports of the first three, none of
which it needs — the frontier, the branch and the change's documents are all on
disk (shared rules 1 and 11).

So when `N > 1`, run **each feature in its own session** and stay a thin
orchestrator here:

```bash
SDD_AUTO_DELEGATED=1 claude -p "/sdd:auto <feature>" --permission-mode acceptEdits
```

- **The guard matters**: `SDD_AUTO_DELEGATED` is what stops a delegated run from
  delegating again. If it is already set in the environment, you *are* the
  delegated run — execute the pipeline below inline and never spawn another.
- **Read the outcome from disk**, never from the sub-session's prose:
  `STATE.md` (`PR_OPEN`, `READY_FOR_PR`, `MERGED`) and `BLOCKED.md` are the
  facts; its final text is a summary for the human. Fold both into your report.
- **Between features, re-read the frontier here** — that is the orchestration
  that cannot be delegated, since closing one feature opens others.
- **Fallback**: no `claude` on PATH, or the command fails before touching
  `STATE.md` → run that feature's pipeline inline and say so in the report. This
  is a cost optimisation; it never blocks a feature and never aborts a run.

A single-feature run (`/sdd:auto` with `N = 1` or a named feature) is already one
session per feature: execute the pipeline inline.

Then, for the feature at hand:

1. **Branch + claim**: check `git ls-remote --heads origin "sdd/<feature>"`. If
   the branch exists, establish **whose** it is before calling it a claim —
   auto's own earlier runs leave branches behind, since a change stays open
   until it merges:
   - `sdd/changes/<feature>/` exists locally → this is **our own in-flight
     change**, not someone else's claim. Resume it per "Resuming a mid-flight
     feature", and report it by its lifecycle state (`ready for PR` /
     `PR open` / `awaiting archive`) — never as `skipped`.
   - no local change directory → the feature is genuinely claimed by someone
     else: skip it (report it as claimed in the final summary) and take the
     next entry.

   No remote branch → `git checkout -b sdd/<feature>` from BASE and, if a remote
   exists, **push the branch immediately** — publishing the claim before doing
   any work, not after.

   **Isolate before branching** (shared rule 10): run
   `sdd_session.py --root . check --feature <feature>`. On `CONFLICT`, auto does
   **not** ask — it applies the worktree per
   `${CLAUDE_PLUGIN_ROOT}/references/isolation.md` (base-ref check →
   `EnterWorktree` → bootstrap from `sdd/project.md` → `claim`) and says so in
   the final report. If the bootstrap the project declares fails, or the project
   declares none and verification then fails on a missing local file, BLOCK the
   feature: that is a real gap in `project.md`, not something to guess around.
   On `CLEAR`, `claim` the feature and continue in place. A resumed feature uses
   `resolve` and enters its existing worktree instead of creating a second one.
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
6. **review + READY_FOR_PR** — **in a fresh session** (shared rule 11). By this
   point the run has filled this context with diffs, test output and panel
   reports, and review is the most expensive phase per request in the flow. It
   needs none of that: its referents are on disk. So delegate it, from the
   feature's working directory:

   ```bash
   claude -p "/sdd:review <feature>. The base branch is <BASE>; do not ask about it." --permission-mode acceptEdits
   ```

   Then **read the result from disk, not from the prose it printed** (rule 11,
   and rule 8's evidence-over-claims): `STATE.md` at `READY_FOR_PR` with a
   recorded `implementation_sha` is the pass. A `BLOCKED.md` written by the
   sub-session is a real block — adopt it and move on to the next feature. Any
   other outcome is a failed verdict: BLOCK.

   The sub-session marks its own usage and exports to the same per-repository
   sink, so metrics stay attributed (`${CLAUDE_PLUGIN_ROOT}/references/metrics.md`).

   **Fallback, stated in the report**: if `claude` is not on PATH, the command
   fails, or it returns without touching `STATE.md`, do the review inline right
   here — a degraded, expensive review beats an abandoned feature. Never let this
   optimisation abort a run.

   Either way the milestones are recorded with BASE explicit — auto recorded it
   in the preconditions, so the base is **never** ambiguous and must never be
   asked. If the sub-session did not record them (or you reviewed inline):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . mark-local-verified <feature>
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_lifecycle.py" --root . mark-ready <feature> --base <BASE>
   ```

   The change's single `STATE.md` then holds `READY_FOR_PR` with BASE, head
   branch, repository, and reviewed implementation SHA. Commit:
   `sdd(<feature>): ready for PR`.
7. **Publish** — follow `${CLAUDE_PLUGIN_ROOT}/skills/ship/SKILL.md`: push,
   open the PR from `sdd/<feature>` to BASE, and record the PR evidence with
   `record-pr`. That skill is the single home for this stretch (shared rule 1);
   auto used to carry its own copy, and two copies of a publishing contract
   drift. Auto's own conversions still apply on top of it: never ask anything,
   and treat every environment limit (no remote, no `gh`, push refused) as a
   **handoff, not a failure** — leave `READY_FOR_PR`, name the exact manual
   action, and continue with the next feature. Never fabricate a URL and never
   stop the run over it.
8. **STOP before archive.** Do not call `/sdd:archive`, update living specs,
   check off the roadmap, consolidate archive metrics, or move the change.
   Those final effects are permitted only once the merge is objectively proven
   — a `MERGED` PR, or the reviewed commit contained in the base branch.
9. **Return to base and continue.** If this feature ran in its own worktree,
    go back to the main worktree (`EnterWorktree` with the original `path`, or
    `ExitWorktree` with `action: "keep"` when auto created it this session) and
    leave the worktree **on disk** — the change is not merged yet, so its work
    must survive. Otherwise `git checkout BASE`. Then take the next entry.
    Never archive or remove a worktree here; that is `/sdd:archive`'s job, after
    the merge is proven.

## Resuming a mid-flight feature

`/sdd:auto <feature>` where `sdd/changes/<feature>/` already exists does NOT start over — it resumes from the change's current phase with the same gate substitutes:

- `BLOCKED.md` present → do not resume: the feature awaits the user's decision. Report it as blocked and take the next roadmap entry; only a run that targeted this single feature ends here.
- Only `proposal.md` → continue at design (the existing proposal counts as approved: the user drove it).
- `proposal.md` + `design.md` → continue at tasks.
- `tasks.md` with unchecked tasks → continue at run.
- All tasks checked, no lifecycle metadata → continue at review.
- `state: READY_FOR_PR` → push/open the PR and record it; do not re-review.
- `state: PR_OPEN` → report the PR and wait for remote review/merge.
- `state: MERGED` → point to `/sdd:archive <feature>`; auto does not archive.

Documents already written by the user's manual phases are treated as approved input — never regenerate them. If the change lives on an existing `sdd/<feature>` branch, switch to it instead of branching anew. This enables the hybrid the gates make expensive: the human drives the thinking phases, auto finishes the mechanical ones.

## Handoff: the steps that stay the user's

Auto is expected to run to the end of the run without the user present, so the
things it cannot do alone — pushing without a remote, opening a PR without `gh`,
merging, archiving — are **handoffs, not failures**. None of them may abort the
run or turn into a question. For every one of them:

1. **Leave nothing uncommitted.** Whatever passed its verification is committed
   on `sdd/<feature>` before auto moves on, so the handoff is a branch the user
   can push, not a dirty tree they must reconstruct.
2. **Leave the next action on disk, not in the conversation.** `STATE.md` is the
   record: `READY_FOR_PR` means "push and open the PR", `PR_OPEN` means "merge
   it", `MERGED` means "`/sdd:archive <feature>`". `/sdd:status` reads exactly
   that, so the handoff survives the session ending (shared rule 1).
3. **Name it in the report** with the exact command, per feature.
4. **Keep going.** A feature awaiting a human step never stops the run: return
   to BASE and take the next roadmap entry.

## The BLOCKED contract

When blocking a feature:

1. Write `sdd/changes/<feature>/BLOCKED.md` (entry format per shared rule 5:
   phase · type · what & why · exact resume command): the exact question(s)
   a human must answer or the findings that persisted, and what was tried.
   This file is the handoff — write it so the user can decide in one read.
2. Commit whatever is consistent (documents + code that passed its
   verification) on `sdd/<feature>` — never leave uncommitted work.
3. Do **not** annotate the roadmap. `BLOCKED.md` is the record, and
   `/sdd:status` derives `⛔` from it; annotating the entry too would duplicate
   derived state into a shared file, which is what makes parallel runs conflict
   (`docs/adr/0001-roadmap-structure-and-concurrency.md`, D5).
4. Return to base as in pipeline step 9 (leaving any worktree on disk — the
   blocked work lives there) and continue with the next entry, or finish if none.

Unblocking is human: the user answers in BLOCKED.md's terms, deletes the
file, and resumes with the normal phase skills on that branch.

## Final report (always, even if everything blocked)

- Per feature: **PR open** (link; archive pending merge) /
  **ready for PR** (exact next action) / **awaiting archive** (already merged →
  `/sdd:archive <feature>`) / **blocked** (phase + one-line reason) /
  **claimed by someone else** (remote branch, no local change) / **skipped**
  (with the reason). Never call a PR-open change shipped or archived, and never
  report one of our own in-flight changes as claimed.
- **Where each feature lives**: if it ran in its own worktree, give the path.
  Without it the user cannot pick the work up — it is not in the directory they
  started the run from. Say that the worktrees stay on disk until archive removes
  them, and that `/sdd:status` lists them.
- Always state that living specs and the definitive roadmap tick remain
  pending until merge, and that the next command after merge is
  `/sdd:archive <feature>`.
- A closing **"yours to run"** list: one line per feature with the single
  command the user has to execute (`git push`, `gh pr create …`, merge the PR,
  `/sdd:archive <feature>`, or the BLOCKED.md question to answer). This is the
  whole point of an unattended run — the user comes back to a list of actions,
  not a transcript to reconstruct.
- If the run proceeded without steering docs, say so first: the panel reviewed
  against weak referents, and fixing that is the highest-value change before
  the next run.
- Cost per feature from `sdd/changes/<feature>/metrics.md` if tracking is on.
- Anything the run revealed about steering docs being too vague to enforce —
  that's the user's lever for making the next auto run better.
