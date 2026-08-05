---
name: doctor
description: Validate SDD state consistency without modifying files. Checks roadmap structure and its dependency graph (cycles, unknown dependencies, order violations), changes, requirements, tasks, archives, blockers, local references, lifecycle metadata, and PR/merge evidence. Use when the user runs /sdd:doctor or asks to diagnose the SDD workspace.
---

Read `${CLAUDE_PLUGIN_ROOT}/rules.md` first (shared rules for all SDD phases).

# SDD — Doctor

Run the deterministic, read-only state validator from the project root:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd-doctor.py" --root .
```

Return its diagnostics and summary verbatim. Do not edit files or attempt to
repair findings. Exit code `0` means there are no errors; warnings alone do not
fail. A non-zero exit code means at least one error was found.

The roadmap's dependency graph is validated as part of this run (`SDD018`-`SDD023`:
duplicate entries, dependencies on entries that do not exist, cycles, an entry
closed before its dependency, unknown metadata keys, a stage with no declared
outcome). When a finding needs the graph itself to be understood — *why* is that
order wrong — show the views rather than describing them:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_roadmap.py" --root . report
```

Then check **machine state**, which the validator above deliberately does not
cover (it lives in the shared git directory, not in the committed project):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . worktrees
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_session.py" --root . orphans
```

`worktrees` lists every worktree **git** knows about (not just the registered
ones) with `RETIRABLE` or `en uso` plus its blockers. Report the retirable ones:
their work has shipped and they are only taking up disk — `sdd_session.py retire
<feature>` closes each. `orphans` adds bindings pointing at a worktree that no
longer exists, which only need `release`.

Label all of it as **machine-local** so nobody looks for it in the repository, and
never retire anything from here: `/sdd:doctor` is read-only. Outside a git
repository both commands error: say so and move on, it is not a project problem.
