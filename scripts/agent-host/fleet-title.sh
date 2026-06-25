#!/usr/bin/env bash
# Live pane-title updater: each agent writes its current task to
# ~/fleet/assign/<agent>.txt; reflect it on the pane border so you can see which
# pane is on which task. Runs as a detached tmux window.
set -uo pipefail
FL="$HOME/fleet"
while tmux has-session -t dash 2>/dev/null; do
  if [ -f "$FL/assign/panes.txt" ]; then
    while read -r a pane repo; do
      [ -n "${pane:-}" ] || continue
      t=$(head -c 56 "$FL/assign/$a.txt" 2>/dev/null | tr -d '\n')
      tmux select-pane -t "$pane" -T "$a · $repo · ${t:-…}" 2>/dev/null || true
    done < "$FL/assign/panes.txt"
  fi
  sleep 4
done
