---
name: doctor
description: Validate SDD state consistency without modifying files. Use when the user runs /sdd:doctor, asks to diagnose the SDD workspace, or wants deterministic checks for roadmap, changes, requirements, tasks, archives, blockers, and local references.
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
