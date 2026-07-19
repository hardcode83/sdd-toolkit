#!/usr/bin/env bash
# codex-adapter-install.sh — wire the shared SDD skills into Codex.
#
# The shared skills and the PreToolUse hook reference files through
# ${CLAUDE_PLUGIN_ROOT}. Claude Code sets that variable; Codex does not, and it
# has no equivalent substitution. This script resolves the *installed* plugin
# root and writes it into ~/.codex/config.toml via `shell_environment_policy.set`,
# so Codex's shell resolves ${CLAUDE_PLUGIN_ROOT} for both the skills' file reads
# and the hook.
#
# The version is resolved at run time (never hardcoded). Re-run this after every
# `codex plugin` update to point at the new version — it is idempotent.
#
# Usage:  scripts/codex-adapter-install.sh
# Env:    CODEX_HOME (default ~/.codex)
set -euo pipefail

CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CONFIG="$CODEX_HOME/config.toml"
CACHE_DIR="$CODEX_HOME/plugins/cache/sdd-toolkit-experimental/sdd-toolkit"
MARKER_START="# >>> sdd-toolkit codex adapter (managed — do not edit by hand) >>>"
MARKER_END="# <<< sdd-toolkit codex adapter (managed) <<<"

# 1. Resolve the installed plugin root: the highest installed version directory.
root=""
if [ -d "$CACHE_DIR" ]; then
  root=$(find "$CACHE_DIR" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -1)
fi
# Fallback: the source checkout this script lives in.
if [ -z "$root" ]; then
  root=$(cd "$(dirname "$0")/.." && pwd)
fi
if [ ! -f "$root/rules.md" ]; then
  echo "error: no installed sdd-toolkit plugin root found under" >&2
  echo "       $CACHE_DIR" >&2
  echo "       Install the plugin first, then re-run:" >&2
  echo "         codex plugin marketplace add \"$(cd "$(dirname "$0")/.." && pwd)\"" >&2
  echo "         codex plugin add sdd-toolkit@sdd-toolkit-experimental" >&2
  exit 1
fi

# 2. Refuse to clobber an unmanaged [shell_environment_policy] table.
if [ -f "$CONFIG" ] && grep -q '^\[shell_environment_policy' "$CONFIG" \
   && ! grep -qF "$MARKER_START" "$CONFIG"; then
  echo "error: $CONFIG already defines a [shell_environment_policy] table outside" >&2
  echo "       this adapter's managed block. Add this key there by hand instead:" >&2
  echo "         [shell_environment_policy.set]" >&2
  echo "         CLAUDE_PLUGIN_ROOT = \"$root\"" >&2
  exit 1
fi

# 3. Rewrite the managed block idempotently (remove any prior one, then append).
mkdir -p "$CODEX_HOME"
tmp=$(mktemp)
if [ -f "$CONFIG" ]; then
  awk -v s="$MARKER_START" -v e="$MARKER_END" '
    $0==s {inblk=1}
    !inblk {print}
    $0==e {inblk=0}
  ' "$CONFIG" | awk 'NF{blank=0} !NF{blank++} blank<2' > "$tmp"
else
  : > "$tmp"
fi
{
  printf '\n%s\n' "$MARKER_START"
  printf '[shell_environment_policy.set]\n'
  printf 'CLAUDE_PLUGIN_ROOT = "%s"\n' "$root"
  printf '%s\n' "$MARKER_END"
} >> "$tmp"
mv "$tmp" "$CONFIG"

echo "ok: CLAUDE_PLUGIN_ROOT -> $root"
echo "    written to $CONFIG"
echo "    Start a fresh Codex thread for it to take effect."
