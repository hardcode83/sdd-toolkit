#!/usr/bin/env bash
# Write one SDD phase's usage (real token counts + estimated cost, subagents
# included) to the change's metrics ledger, aggregating the OTel rows tagged
# for that feature/phase by usage-sink.py.
# Usage: usage-phase.sh <feature> <phase>
# Re-running recomputes the phase totals and replaces the row (safe for the
# run phase's `next` mode). Silent no-op if tracking is not enabled.
set -euo pipefail
export LC_ALL=C

feature="${1:?usage: usage-phase.sh <feature> <phase>}"
phase="${2:?usage: usage-phase.sh <feature> <phase>}"
root=$(pwd)
log="$root/.sdd-usage/otel.jsonl"
ledger="$root/sdd/changes/$feature/metrics.md"

[ -f "$log" ] || { echo "usage tracking not enabled — skipping"; exit 0; }
command -v jq >/dev/null || { echo "jq not found — skipping"; exit 0; }
[ -d "$root/sdd/changes/$feature" ] || { echo "no such change: $feature" >&2; exit 1; }

task="$feature/$phase"
row=$(jq -rs --arg t "$task" '
  map(select(.task == $t)) |
  [ ([.[] | select(.metric=="tokens" and .type=="input")  | .value] | add // 0 | round),
    ([.[] | select(.metric=="tokens" and .type=="output") | .value] | add // 0 | round),
    ([.[] | select(.metric=="tokens" and (.type=="cacheRead" or .type=="cacheCreation")) | .value] | add // 0 | round),
    ([.[] | select(.metric=="cost") | .value] | add // 0),
    ([.[] | select(.model != null) | .model] | unique | join(" ")),
    ([.[] | select(.source=="subagent")] | length)
  ] | @tsv' "$log")

IFS=$'\t' read -r t_in t_out t_cache cost models sub <<<"$row"
if [ "$t_in" = "0" ] && [ "$t_out" = "0" ]; then
  echo "no usage recorded yet for $task (export interval is ~10s — retry shortly)"
  exit 0
fi
cost=$(awk -v c="$cost" 'BEGIN{printf "%.4f", c}')
note=""
[ "${sub:-0}" -gt 0 ] && note="incl. subagents"

if [ ! -f "$ledger" ]; then
  printf '# Metrics: %s\n\n| date | phase | models | tokens in | tokens out | tokens cache | cost USD (est) | notes |\n|---|---|---|---|---|---|---|---|\n' "$feature" > "$ledger"
fi
tmp=$(mktemp)
grep -v "^| [0-9-]\{10\} | $phase |" "$ledger" > "$tmp" || true
mv "$tmp" "$ledger"
printf '| %s | %s | %s | %s | %s | %s | %s | %s |\n' \
  "$(date +%F)" "$phase" "${models:-?}" "$t_in" "$t_out" "$t_cache" "$cost" "$note" >> "$ledger"
echo "metrics: $phase → in=$t_in out=$t_out cache=$t_cache ≈\$$cost ${note:+($note)}"
