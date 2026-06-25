#!/usr/bin/env bash
# Talk to a running agent from anywhere (terminal or phone shell):
#   bash fleet-talk.sh <agent-number> <message...>
# e.g.  fleet-talk.sh 1 focus on the wallet-connect flow first
# (Or just tap the agent's pane in the dashboard and type directly — same thing.)
set -uo pipefail
FL="$HOME/fleet"
n="${1:-}"; shift || true; msg="$*"
[ -n "$n" ] && [ -n "$msg" ] || { echo "usage: fleet-talk.sh <agent#> <message>"; exit 1; }
pane=$(awk -v a="a$n" '$1==a{print $2}' "$FL/assign/panes.txt" 2>/dev/null)
[ -n "$pane" ] || { echo "no agent a$n (see $FL/assign/panes.txt)"; exit 1; }
tmux send-keys -t "$pane" "$msg" Enter && echo "→ a$n: $msg"
