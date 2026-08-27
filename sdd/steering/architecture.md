---
phases: [design, tasks]
---

# Architecture

## System shape

The toolkit is a plugin distributed to coding runtimes. Shared skills, rules,
templates, references, scripts, hooks, and logical reviewer definitions form
the plugin layer. Consumer repositories hold SDD persistence (`sdd/`),
steering, specs, changes, and optional project reviewers. Runtime adapters
translate shared lifecycle decisions into Claude or Codex execution primitives.

## Standing decisions

- The repository is the toolkit implementation; its Python scripts use only
  the standard library.
- Lifecycle state and merge evidence are authoritative in `STATE.md` and the
  deterministic lifecycle helpers, not in model memory.
- Shared logical behavior must be selected before runtime-specific invocation.

## Rules

- Preserve the plugin/project boundary: do not copy internal tests or CI into
  consumer projects.
- Any distributed behavior change must update both plugin manifests together.
- Changes to lifecycle transitions, reviewer dispatch, or merge gates require
  executable tests and fixture coverage.

## Anti-patterns

- Independently maintained Claude and Codex copies of reviewer methodology.
- Treating a missing reviewer or malformed result as a passing gate.
- Encoding project-specific behavior in the plugin instead of project SDD data.
