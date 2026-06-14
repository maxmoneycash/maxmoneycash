#!/bin/bash
# Claude Code SessionEnd hook: refresh the README token stats for the coding
# session that just finished.
#
# Wired up two ways (see scripts/install_claude_hook.sh and .claude/settings.json):
#   - per-repo : .claude/settings.json in this repo
#   - global   : ~/.claude/settings.json (every session, any repo)
#
# Safe to run anywhere. It no-ops unless it is running on the Mac that actually
# holds the ccusage logs AND inside the owner's clone of this repo. The heavy
# work is detached to the background so session teardown never waits on ccusage
# or the network.
set -euo pipefail

# Resolve THIS repo from the script's own location (not the session's cwd), so a
# global hook fired from any other repo still drives the maxmoneycash collector.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COLLECTOR="$REPO_DIR/scripts/collect_tokens.sh"
LOG="$HOME/Library/Logs/tokenstats.log"
LOCKDIR="${TMPDIR:-/tmp}/tokenstats.lock.d"

run_worker() {
  # Atomic single-flight lock (mkdir is atomic; macOS has no flock by default).
  if ! mkdir "$LOCKDIR" 2>/dev/null; then
    echo "$(date -u +%FT%TZ) hook: collection already running, skip" >>"$LOG"
    return 0
  fi
  trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT
  echo "$(date -u +%FT%TZ) hook: session ended, collecting tokens" >>"$LOG"
  if bash "$COLLECTOR" >>"$LOG" 2>&1; then
    echo "$(date -u +%FT%TZ) hook: done" >>"$LOG"
  else
    echo "$(date -u +%FT%TZ) hook: collector failed (see above)" >>"$LOG"
  fi
}

# Background worker entrypoint.
if [ "${1:-}" = "--worker" ]; then
  run_worker
  exit 0
fi

# --- Front door (what the hook invokes): guard, then detach. ----------------
# Only the Mac with the local usage logs should ever collect.
[ "$(uname)" = "Darwin" ] || exit 0
{ command -v bunx || command -v bun ; } >/dev/null 2>&1 || exit 0
[ -f "$COLLECTOR" ] || exit 0
# Only the owner's clone — never auto-push from a fork or someone else's machine.
origin="$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null || true)"
case "$origin" in
  *maxmoneycash/maxmoneycash*) : ;;
  *) exit 0 ;;
esac

mkdir -p "$HOME/Library/Logs"
nohup bash "${BASH_SOURCE[0]}" --worker >/dev/null 2>&1 &
disown 2>/dev/null || true
exit 0
