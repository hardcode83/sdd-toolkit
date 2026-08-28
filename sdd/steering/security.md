---
phases: [design, run]
---

# Security

## Data classification

The toolkit handles repository source, SDD requirements/design/tasks, review
findings, and local runtime configuration. Credentials and provider secrets are
machine/runtime concerns and must not be committed to plugin or SDD artifacts.

## Rules

- Reviewer agents are read-only and must not implement fixes.
- Missing, unavailable, malformed, or incomplete reviewer output must fail
  closed; it must never be converted to PASS.
- Plugin installation and runtime adapters must not require users to copy
  prompts or configure untracked reviewer definitions manually.
- Execution-boundary changes must preserve sandbox/read-only policy and validate
  reviewer identity before accepting results.

## Review triggers

Review execution changes, plugin packaging, runtime/provider adapters, custom
agent resources, result parsing, and any code that can turn an unavailable
review into an accepted gate.
