#!/usr/bin/env bash
# Mark the active feature/phase for usage attribution and ensure the local
# OTLP sink is running. Called at the start of each SDD phase.
# Usage: usage-mark.sh <feature> <phase>
# Silent no-op if telemetry isn't enabled for this project.
set -euo pipefail

feature="${1:?usage: usage-mark.sh <feature> <phase>}"
phase="${2:?usage: usage-mark.sh <feature> <phase>}"
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(pwd)

# One sink, one log, one pidfile for the whole repository — including its
# worktrees, which all export to the same port.
# shellcheck source=usage-dir.sh
. "$here/usage-dir.sh"
sdd_usage_resolve "$root"
settings="$SDD_USAGE_MAIN/.claude/settings.json"

command -v jq >/dev/null || exit 0
[ -f "$settings" ] || exit 0
enabled=$(jq -r '.env.CLAUDE_CODE_ENABLE_TELEMETRY // empty' "$settings")
[ "$enabled" = "1" ] || exit 0

dir="$SDD_USAGE_DIR"
mkdir -p "$dir/tasks"
# Attribution is PER SESSION. A single shared pointer was last-writer-wins, so
# two concurrent sessions billed each other's tokens to the wrong feature. The
# sink already records `session.id` on every datapoint, so it can resolve the
# right file. `current-task` stays as the fallback for datapoints that arrive
# without a session id, and for readers older than this change.
printf '%s/%s' "$feature" "$phase" > "$dir/current-task"
if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
  printf '%s/%s' "$feature" "$phase" > "$dir/tasks/$CLAUDE_CODE_SESSION_ID"
fi

# ensure sink (port from the configured OTLP endpoint)
port=4318
ep=$(jq -r '.env.OTEL_EXPORTER_OTLP_ENDPOINT // empty' "$settings")
[[ "$ep" =~ :([0-9]+)/?$ ]] && port="${BASH_REMATCH[1]}"
pidfile="$dir/sink.pid"
if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
  exit 0
fi
SDD_USAGE_DIR="$dir" nohup python3 "$here/usage-sink.py" "$port" >/dev/null 2>&1 &
echo $! > "$pidfile"
echo "usage sink started on 127.0.0.1:$port"
