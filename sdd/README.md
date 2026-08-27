# SDD — Spec-Driven Development

This directory is the persistent project layer for the SDD Toolkit: live
specifications, in-flight changes, steering rules, and lifecycle state live in
files rather than in a model session.

- `project.md` records this repository's stack, exact validation commands,
  conventions, and worktree policy.
- `steering/` contains selectively loaded standing rules.
- `specs/` records current behavior in EARS form and is updated on archive.
- `changes/` contains proposals, designs, tasks, evidence, and lifecycle state.
- `changes/archive/` contains completed changes.
- `roadmap.md` is optional and is created only when a planning document is
  intentionally ingested.

The normal flow is `/sdd:new` → `/sdd:design` → `/sdd:tasks` → `/sdd:run` →
`/sdd:review` → PR → merge → `/sdd:archive`. Each phase waits for approval.
`/sdd:doctor` is deterministic and read-only.
