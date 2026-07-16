---
name: auto
model: sonnet
description: Run SDD features end-to-end without human intervention - consumes roadmap entries through new/design/tasks/run/review/archive with automated gate substitutes, one branch+PR per feature, and a BLOCKED queue for anything needing a human decision. Use when the user runs /sdd:auto, optionally with a count or feature name.
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

1. **Branch**: `git checkout -b sdd/<feature>` from BASE.
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
6. **review** — follow the review skill at feature scale. Verdict must be
   ready-to-archive; otherwise BLOCK.
7. **archive** — follow the archive skill (specs merge, metrics
   consolidation, roadmap tick). Commit: `sdd(<feature>): archive`.
8. **Publish**: if a remote and `gh` are available, push and open a PR from
   `sdd/<feature>` to BASE — title `SDD: <feature>`, body = the proposal's
   Why/What + panel verdict + link to the archived change; end the body
   with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
   No remote → leave the branch and say so.
9. `git checkout BASE` and continue with the next entry.

## The BLOCKED contract

When blocking a feature:

1. Write `sdd/changes/<feature>/BLOCKED.md`: which phase blocked, the exact
   question(s) a human must answer or the findings that persisted, and what
   was tried. This file is the handoff — write it so the user can decide in
   one read.
2. Commit whatever is consistent (documents + code that passed its
   verification) on `sdd/<feature>` — never leave uncommitted work.
3. Annotate the roadmap entry with ` ⛔ blocked`.
4. Return to BASE and continue with the next entry (or finish if none).

Unblocking is human: the user answers in BLOCKED.md's terms, deletes the
file, and resumes with the normal phase skills on that branch.

## Final report (always, even if everything blocked)

- Per feature: **shipped** (PR link) / **blocked** (phase + one-line reason)
  / **skipped**.
- Cost per feature from `sdd/changes/<feature>/metrics.md` if tracking is on.
- Anything the run revealed about steering docs being too vague to enforce —
  that's the user's lever for making the next auto run better.
