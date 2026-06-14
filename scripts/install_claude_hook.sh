#!/bin/bash
# Install the SessionEnd token-stats hook into the USER-level Claude Code
# settings (~/.claude/settings.json), so EVERY coding session in ANY repo
# refreshes the README stats — not just sessions opened in this repo.
#
# Idempotent: re-running won't add a duplicate. Run once on the Mac:
#   bash scripts/install_claude_hook.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$REPO_DIR/scripts/claude_session_hook.sh"
SETTINGS="$HOME/.claude/settings.json"

[ -f "$HOOK" ] || { echo "missing hook script: $HOOK" >&2; exit 1; }
mkdir -p "$HOME/.claude"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"

CMD="bash \"$HOOK\""

python3 - "$SETTINGS" "$CMD" <<'PY'
import json, sys
path, cmd = sys.argv[1], sys.argv[2]
with open(path) as f:
    try:
        cfg = json.load(f)
    except json.JSONDecodeError:
        cfg = {}

hooks = cfg.setdefault("hooks", {})
session_end = hooks.setdefault("SessionEnd", [])

already = any(
    "claude_session_hook.sh" in h.get("command", "")
    for group in session_end
    for h in group.get("hooks", [])
)

if already:
    print(f"hook already present in {path}; nothing to do")
else:
    session_end.append(
        {"hooks": [{"type": "command", "command": cmd, "timeout": 30}]}
    )
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print(f"added SessionEnd hook to {path}")
PY

echo "every coding session will now refresh stats (logs: $HOME/Library/Logs/tokenstats.log)"
