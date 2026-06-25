#!/usr/bin/env bash
# Generator: keep the queue stocked with PR-sized tasks that serve the mission,
# mined per repo from recent commits + file list + GitHub issues labeled 'agent'.
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
FLEET="$HOME/fleet"; WORK="$HOME/work"; Q="$FLEET/queue"
mkdir -p "$Q"
REPOS_FILE="$FLEET/repos.txt"; MISSION_FILE="$FLEET/mission.txt"
QUEUE_MAX="${QUEUE_MAX:-8}"; GEN_GAP="${GEN_GAP:-90}"; PER_REPO="${PER_REPO:-3}"; CEIL="${CEIL:-0.92}"
log(){ echo "[$(date -u +%H:%M:%S) gen] $*"; }
capped(){ local p; p=$(bunx --bun ccusage@latest blocks --active --json 2>/dev/null \
  | jq -r '.blocks[0].projection.percent // 0' 2>/dev/null); awk -v p="${p:-0}" -v c="$CEIL" 'BEGIN{exit !((p+0)/100>=c)}'; }
qcount(){ ls "$Q"/*.task 2>/dev/null | wc -l | tr -d ' '; }
addtask(){ local f="$Q/$(date -u +%s)-$RANDOM.task"; printf '%s\n%s\n' "$1" "$2" > "$f"; log "queued [$1] $2"; }
mission(){ [ -f "$MISSION_FILE" ] && cat "$MISSION_FILE" || echo "Move the project forward with high-value, PR-sized improvements."; }

i=0; log "online"
while true; do
  mapfile -t REPOS < "$REPOS_FILE" 2>/dev/null || REPOS=()
  [ "${#REPOS[@]}" -gt 0 ] || { sleep 60; continue; }
  if [ "$(qcount)" -ge "$QUEUE_MAX" ]; then sleep "$GEN_GAP"; continue; fi
  if capped; then sleep "$GEN_GAP"; continue; fi
  repo="${REPOS[$((i % ${#REPOS[@]}))]}"; i=$((i+1))
  dir="$WORK/$repo"; [ -d "$dir/.git" ] || { log "no repo $repo"; continue; }
  cd "$dir"
  # explicit human asks first: GitHub issues labeled 'agent'
  gh issue list --label agent --state open --json title --jq '.[].title' 2>/dev/null | while read -r t; do
    [ -n "$t" ] && addtask "$repo" "$t"; done
  recent=$(git log --oneline -20 2>/dev/null)
  tree=$(git ls-files 2>/dev/null | head -80)
  prompt="MISSION:
$(mission)

Repo: '$repo'
Recent commits:
$recent

Files:
$tree

Propose up to $PER_REPO concrete, PR-sized tasks that best serve the MISSION.
Favor finishing incomplete features, fixing what's broken, and demo-ready polish.
Each task doable in ONE focused PR. No vague tasks, no giant rewrites.
Output ONLY task titles, one per line, imperative voice, no numbering."
  log "mining $repo"
  claude -p "$prompt" --dangerously-skip-permissions 2>/dev/null | grep -vE '^[[:space:]]*$' | head -"$PER_REPO" | while read -r t; do
    t=$(echo "$t" | sed -E 's/^[-*0-9.) ]+//')
    [ -n "$t" ] && addtask "$repo" "$t"; done
  sleep "$GEN_GAP"
done
