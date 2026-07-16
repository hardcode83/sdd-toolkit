#!/usr/bin/env bash
# Mark the active feature/phase for usage attribution and ensure the local
# OTLP sink is running. Called at the start of each SDD phase.
# Usage: usage-mark.sh <feature> <phase>
# Silent no-op if telemetry isn't enabled for this project.
set -euo pipefail

feature="${1:?usage: usage-mark.sh <feature> <phase>}"
phase="${2:?usage: usage-mark.sh <feature> <phase>}"
root=$(pwd)
settings="$root/.claude/settings.json"

command -v jq >/dev/null || exit 0
[ -f "$settings" ] || exit 0
enabled=$(jq -r '.env.CLAUDE_CODE_ENABLE_TELEMETRY // empty' "$settings")
[ "$enabled" = "1" ] || exit 0

dir="$root/.sdd-usage"
mkdir -p "$dir"
printf '%s/%s' "$feature" "$phase" > "$dir/current-task"

# ensure sink (port from the configured OTLP endpoint)
port=4318
ep=$(jq -r '.env.OTEL_EXPORTER_OTLP_ENDPOINT // empty' "$settings")
[[ "$ep" =~ :([0-9]+)/?$ ]] && port="${BASH_REMATCH[1]}"
pidfile="$dir/sink.pid"
if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
  exit 0
fi
SDD_USAGE_DIR="$dir" nohup python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/usage-sink.py" "$port" >/dev/null 2>&1 &
echo $! > "$pidfile"
echo "usage sink started on 127.0.0.1:$port"
