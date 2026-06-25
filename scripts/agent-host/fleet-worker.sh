#!/usr/bin/env bash
# One fleet worker: claim a task -> run it as a bounded Claude job in an isolated
# git worktree -> open a PR -> repeat. PR-only, never main. Paced under Max limits.
# Streams the live agent work to the pane (formatted) so you can watch it.
#   bash fleet-worker.sh <id>
set -uo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.bun/bin:$HOME/.foundry/bin:/usr/local/go/bin:$PATH"
export FORCE_COLOR=1 CLICOLOR_FORCE=1
ID="${1:-1}"
FLEET="$HOME/fleet"; WORK="$HOME/work"
Q="$FLEET/queue"; CUR="$FLEET/cur"; DONE="$FLEET/done"; FAIL="$FLEET/failed"; LOGD="$FLEET/log"; WT="$FLEET/wt"
mkdir -p "$Q" "$CUR" "$DONE" "$FAIL" "$LOGD" "$WT"
WAVE_GAP="${WAVE_GAP:-15}"; BACKOFF="${BACKOFF:-1800}"; CEIL="${CEIL:-0.95}"; JOB_TIMEOUT="${JOB_TIMEOUT:-1800}"

# colors
R=$'\e[0m'; D=$'\e[2m'; B=$'\e[1m'; CY=$'\e[36m'; GR=$'\e[32m'; YE=$'\e[33m'; RE=$'\e[31m'; MA=$'\e[1;35m'
hr(){ printf '%s\n' "${D}────────────────────────────────────────────────────────────────${R}"; }
ts(){ date -u +%H:%M:%S; }
say(){ printf '%s\n' "$*"; }

capped(){ local p; p=$(bunx --bun ccusage@latest blocks --active --json 2>/dev/null \
  | jq -r '.blocks[0].projection.percent // 0' 2>/dev/null); awk -v p="${p:-0}" -v c="$CEIL" 'BEGIN{exit !((p+0)/100>=c)}'; }
claim(){ local f t; for f in "$Q"/*.task; do [ -e "$f" ] || return 1
  t="$CUR/w$ID-$(basename "$f")"; if mv -n "$f" "$t" 2>/dev/null; then echo "$t"; return 0; fi; done; return 1; }

say "${GR}${B}● worker $ID online${R} ${D}$(ts)${R}"
idle_note=1
while true; do
  if capped; then say "${YE}⏸ w$ID capped — sleeping ${BACKOFF}s${R} ${D}$(ts)${R}"; sleep "$BACKOFF"; continue; fi
  task=$(claim) || { [ "$idle_note" = 1 ] && { say "${D}· w$ID idle — waiting for tasks ($(ts))${R}"; idle_note=0; }; sleep 20; continue; }
  idle_note=1
  repo=$(sed -n '1p' "$task"); title=$(sed -n '2,$p' "$task" | tr '\n' ' ')
  dir="$WORK/$repo"
  [ -d "$dir/.git" ] || { say "${RE}✗ w$ID no repo $repo${R}"; mv "$task" "$FAIL/"; continue; }
  hr
  say "${GR}${B}▶ w$ID  [$repo]${R}  $title"
  cd "$dir" || { mv "$task" "$FAIL/"; continue; }
  git fetch -q origin 2>/dev/null || true
  def=$(git remote show origin 2>/dev/null | sed -n 's/.*HEAD branch: //p'); def="${def:-main}"
  branch="agent/$(date -u +%Y%m%d-%H%M%S)-w$ID"
  wt="$WT/w$ID-$$"; rm -rf "$wt"
  if ! git worktree add -q -b "$branch" "$wt" "origin/$def" 2>>"$LOGD/w$ID.log"; then
    say "${RE}✗ w$ID worktree failed [$repo]${R}"; mv "$task" "$FAIL/"; continue; fi
  say "${D}  branch $branch · worktree ready · running claude…${R}"
  cd "$wt" || { mv "$task" "$FAIL/"; continue; }
  prompt="You are an autonomous engineer working UNATTENDED on the repo '$repo'.
Task: $title
Rules: make the SMALLEST change that satisfies the task; do NOT refactor unrelated
code; work ONLY in this repo; if the task is ambiguous, risky, or needs a human
decision, make NO file changes and instead write a one-paragraph note explaining
why. If a quick build/lint/test exists, run it and ensure it passes."
  # stream claude's live work into the pane (dim, prefixed), also keep a log
  timeout "$JOB_TIMEOUT" claude -p "$prompt" --dangerously-skip-permissions 2>&1 \
    | tee -a "$LOGD/w$ID.log" | sed -u "s/^/${D}  │ ${R}/"
  rc=${PIPESTATUS[0]}
  if [ "$rc" -eq 0 ]; then
    if [ -z "$(git status --porcelain)" ]; then
      say "${YE}◦ w$ID no-op${R} [$repo] $title"; mv "$task" "$DONE/"
    else
      git add -A
      git -c user.name=cairn-fleet -c user.email=fleet@cairn commit -qm "fleet: $title" 2>>"$LOGD/w$ID.log"
      if git push -q -u origin "$branch" 2>>"$LOGD/w$ID.log"; then
        if url=$(gh pr create --fill --head "$branch" 2>>"$LOGD/w$ID.log"); then
          say "${MA}✔ w$ID PR OPENED${R} ${B}[$repo]${R} $url"
          echo "$(date -u +%FT%TZ) [$repo] $title -> $url" >> "$LOGD/prs.log"
        else say "${YE}⚠ w$ID pushed but PR failed [$repo]${R}"; fi
        mv "$task" "$DONE/"
      else say "${RE}✗ w$ID push failed [$repo]${R}"; mv "$task" "$FAIL/"; fi
    fi
  else
    say "${RE}✗ w$ID failed/timeout (rc=$rc) [$repo] $title${R}"; mv "$task" "$FAIL/"
  fi
  cd "$dir"; git worktree remove --force "$wt" 2>/dev/null || true; git branch -D "$branch" 2>/dev/null || true
  say "${D}  w$ID done · next in ${WAVE_GAP}s${R}"; hr
  sleep "$WAVE_GAP"
done
