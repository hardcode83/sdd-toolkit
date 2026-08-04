#!/usr/bin/env bash
# Resolve the ONE .sdd-usage directory shared by every worktree of this repo.
#
# All sessions of a project export OTel to the same endpoint: the port lives in
# the project's versioned `.claude/settings.json` and is read at session start,
# so it is the same for every session and every worktree. That makes a
# per-worktree ledger actively wrong — only the first sink would bind the port,
# every session's datapoints would land in that one worktree's log, and the rest
# would look like they cost nothing. Resolving to the main worktree gives one
# sink, one pidfile and one log, with attribution done per session id inside
# usage-sink.py. See docs/adr/0001-roadmap-structure-and-concurrency.md.
#
# Sourced, not executed. Sets SDD_USAGE_MAIN and SDD_USAGE_DIR.
# With no git repository (or no git), it degrades to the given root, which is the
# pre-worktree behaviour.

sdd_usage_resolve() {
  local root="${1:-$(pwd)}" common main
  common=$(git -C "$root" rev-parse --git-common-dir 2>/dev/null || true)
  if [ -n "$common" ]; then
    # git answers relatively from the main worktree (`.git`) and absolutely from
    # a linked one, so both shapes have to be handled.
    case "$common" in
      /*) ;;
      *) common="$root/$common" ;;
    esac
    main=$(cd "$common/.." 2>/dev/null && pwd) || main="$root"
  else
    main="$root"
  fi
  SDD_USAGE_MAIN="$main"
  SDD_USAGE_DIR="$main/.sdd-usage"
}
