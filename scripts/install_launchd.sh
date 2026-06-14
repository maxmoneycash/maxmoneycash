#!/bin/bash
# Install / refresh the tokenstats launchd agent on this Mac.
#
# Renders scripts/launchd/com.maxmoneycash.tokenstats.plist with this machine's
# paths into ~/Library/LaunchAgents/, (re)loads it, and kicks it once so today's
# stats push immediately. Idempotent: safe to re-run after a git pull.
#
#   bash scripts/install_launchd.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.maxmoneycash.tokenstats"
TEMPLATE="$REPO_DIR/scripts/launchd/$LABEL.plist"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

[ -f "$TEMPLATE" ] || { echo "missing template: $TEMPLATE" >&2; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

# Render template -> destination with this machine's real paths.
sed -e "s|__REPO_DIR__|$REPO_DIR|g" -e "s|__HOME__|$HOME|g" "$TEMPLATE" > "$DEST"

# Reload: drop any existing definition (ignore if not loaded), then bootstrap.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$DEST"
launchctl enable "$DOMAIN/$LABEL"

# Kick it once now so the current day's stats collect and push immediately.
launchctl kickstart -k "$DOMAIN/$LABEL"

echo "installed $LABEL -> $DEST"
echo "kicked once; watch: tail -f $HOME/Library/Logs/tokenstats.log"
