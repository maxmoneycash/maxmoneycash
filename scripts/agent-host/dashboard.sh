#!/usr/bin/env bash
# Build/refresh the 'dash' tmux session — a phone-friendly wall you view from
# your browser via ttyd over Tailscale. One pane per running agent (falls back
# to the runner log until the multi-agent runner is live), plus htop, live
# ccusage, and the worklist.
#
#   bash dashboard.sh           # create/attach the dash session
#   ttyd serves:  tmux new -A -s dash   (see ttyd.service)
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
SESSION=dash
LOGDIR="$HOME/agent-logs"; mkdir -p "$LOGDIR"
RUNLOG="$HOME/agent-runner.log"; touch "$RUNLOG"
WORKLIST="$HOME/work/maxmoneycash/scripts/agent-host/worklist.md"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  exec tmux attach -t "$SESSION"
fi

# Window 1 "agents": one pane per agent log; fall back to the single runner log
shopt -s nullglob
logs=( "$LOGDIR"/agent-*.log )
[ ${#logs[@]} -gt 0 ] || logs=( "$RUNLOG" )
tmux new-session -d -s "$SESSION" -n agents "tail -F '${logs[0]}'"
for ((i=1; i<${#logs[@]}; i++)); do
  tmux split-window -t "$SESSION":agents "tail -F '${logs[$i]}'"
  tmux select-layout -t "$SESSION":agents tiled >/dev/null
done

# Window 2 "system": htop + live usage + the queue
tmux new-window -t "$SESSION" -n system "htop 2>/dev/null || top"
tmux split-window -h -t "$SESSION":system \
  "watch -n 30 'npx -y ccusage@latest blocks --active 2>/dev/null | tail -n 20'"
tmux split-window -v -t "$SESSION":system \
  "watch -n 30 'sed -n 1,40p \"$WORKLIST\" 2>/dev/null'"
tmux select-layout -t "$SESSION":system tiled >/dev/null

tmux select-window -t "$SESSION":agents
echo "dash ready — attach with: tmux attach -t dash"
