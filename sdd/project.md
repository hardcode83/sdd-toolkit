# Project Steering

## Overview

SDD Toolkit is a Claude Code plugin with a Codex adapter. It provides a
file-backed Spec-Driven Development lifecycle, deterministic lifecycle scripts,
review-panel agents, templates, and internal validation for toolkit
releases.

## Stack

- Markdown skills, rules, templates, and reference documentation.
- Python 3 standard-library scripts and `unittest` tests.
- Claude Code and Codex plugin manifests; no application framework or runtime
  service is defined in this repository.
- GitHub Actions validates the plugin and its fixtures.

## Commands

- Test: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v`
- Validate all toolkit contracts: `python3 scripts/validate_toolkit.py all`
- Validate manifests: `python3 scripts/validate_toolkit.py manifests`
- Validate skills: `python3 scripts/validate_toolkit.py skills`
- Validate plugin/project boundary: `python3 scripts/validate_toolkit.py boundary`
- Validate doctor fixtures: `python3 scripts/validate_toolkit.py fixtures`
- Doctor a project: `python3 scripts/sdd-doctor.py --root <project>`
- No local application build or run command is defined.

## Worktree bootstrap

isolation: on-conflict

Nothing is copied or installed for a fresh worktree; this repository has no
declared per-worktree database, service stack, or exclusive runtime resource.
There is no teardown command because no stack is brought up per worktree.

## Conventions

- Keep plugin behavior in `skills/`, `agents/`, `scripts/`, `templates/`,
  `references/`, and `rules.md`; keep project persistence under `sdd/`.
- Preserve the existing SDD change/state contracts and fail-closed gates.
- Runtime-specific resources must remain adapters or generated artifacts, not
  independently maintained methodology copies.
- Tests are executable specifications and fixtures are part of the contract.

## Context

- Repository: https://github.com/hardcode83/sdd-toolkit
- CI: `.github/workflows/validate-toolkit.yml`
- Codex distribution: `.codex-plugin/plugin.json` and `docs/codex.md`
- No project MCPs, LSPs, usage metrics, or optional project reviewers enabled.
