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
