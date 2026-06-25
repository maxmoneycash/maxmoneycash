#!/usr/bin/env bash
# Keep the fleet working: nudge any agent that's gone idle (not actively running,
# screen unchanged) back onto the next task. Runs as a detached tmux window.
set -uo pipefail
FL="$HOME/fleet"
declare -A LAST IDLE
NUDGE="Keep going — pick the next highest-value task toward the demo (DUE TODAY), implement it, build it (the pre-push hook gates broken builds), and merge to main. Do not stop until I say so."
while tmux has-session -t dash 2>/dev/null; do
  [ -f "$FL/assign/panes.txt" ] || { sleep 60; continue; }
  while read -r a pane repo; do
    [ -n "${pane:-}" ] || continue
    cap=$(tmux capture-pane -t "$pane" -p 2>/dev/null)
    # claude shows "esc to interrupt" only while actively working -> not idle
    if echo "$cap" | grep -q 'esc to interrupt'; then IDLE[$pane]=0; LAST[$pane]="busy"; continue; fi
    snap=$(echo "$cap" | grep -vE '^\s*$' | tail -8 | md5sum | cut -d' ' -f1)
    if [ "$snap" = "${LAST[$pane]:-}" ]; then IDLE[$pane]=$(( ${IDLE[$pane]:-0} + 1 )); else IDLE[$pane]=0; fi
    LAST[$pane]="$snap"
    if [ "${IDLE[$pane]:-0}" -ge 2 ]; then
      tmux send-keys -t "$pane" -l "$NUDGE"; sleep 1; tmux send-keys -t "$pane" Enter; sleep 1; tmux send-keys -t "$pane" Enter
      IDLE[$pane]=0
      echo "[$(date -u +%H:%M:%S)] nudged $a (was idle)"
    fi
  done < "$FL/assign/panes.txt"
  sleep 90
done
