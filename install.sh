#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$ROOT/ses.py" ] || { echo "Run this script from a clone of opencode-session-search."; exit 1; }
[ -f "$ROOT/plugin/index.js" ] || { echo "plugin/index.js is missing."; exit 1; }

if command -v uv >/dev/null 2>&1; then
  uv tool install --force "$ROOT"
elif command -v pipx >/dev/null 2>&1; then
  pipx install --force "$ROOT"
else
  echo "uv or pipx is required. Install uv: https://docs.astral.sh/uv/"
  exit 1
fi

SES="$(command -v ses || true)"
if [ -z "$SES" ]; then
  if command -v uv >/dev/null 2>&1; then
    SES="$(uv tool dir --bin)/ses"
  else
    SES="$HOME/.local/bin/ses"
  fi
fi
[ -x "$SES" ] || { echo "ses binary not found at $SES"; exit 1; }

CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
PLUGIN="$CONFIG/plugins/opencode-session-search"
COMMAND="$CONFIG/commands"
mkdir -p "$PLUGIN" "$COMMAND"
cp "$ROOT/plugin/index.js" "$PLUGIN/index.js"
cp "$ROOT/plugin/package.json" "$PLUGIN/package.json"
printf '{"bin":"%s"}\n' "$SES" > "$PLUGIN/config.json"
cp "$ROOT/command/ses.md" "$COMMAND/ses.md"

echo "CLI:     $SES"
echo "Plugin:  $PLUGIN"
echo "Command: $COMMAND/ses.md"
echo "Run 'opencode reload' or restart OpenCode."

case ":$PATH:" in
  *":$(dirname "$SES"):"*) ;;
  *) echo "Note: $(dirname "$SES") is not on PATH. The plugin uses the absolute path; add it to call ses directly." ;;
esac
