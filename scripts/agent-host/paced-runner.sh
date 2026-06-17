#!/usr/bin/env bash
# Paced overnight runner — runs Claude Code jobs from worklist.md while
# respecting the Max plan's 5-hour / weekly limits.
#
# Strategy (conservative v0, tuned live on the box):
#   - Take the first unchecked task from worklist.md.
#   - Run it as ONE bounded headless Claude Code job on a fresh branch.
#   - On success: commit the branch (and push + PR if PUSH=1), check the task off.
#   - If the job fails OR Claude reports a usage limit: back off until the next
#     5-hour window, then resume. A non-zero exit is always treated as "back off"
#     — safe even for transient errors.
#   - Between jobs, log `ccusage blocks --active` for visibility and sleep WAVE_GAP.
#
# It never sets ANTHROPIC_API_KEY, so when the subscription is capped the job
# simply fails and the runner sleeps — it never spends metered API dollars.
#
#   bash paced-runner.sh            # run the loop in the foreground
#   bash paced-runner.sh --install  # install as a systemd --user service + start
#   bash paced-runner.sh --once     # run a single task and exit (for testing)
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
ROOT="$HOME/work"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORKLIST="$HERE/worklist.md"
LOG="$HOME/agent-runner.log"

WAVE_GAP="${WAVE_GAP:-300}"          # seconds between jobs when not capped
BACKOFF="${BACKOFF:-1800}"           # seconds to sleep after a failure / cap hit
PUSH="${PUSH:-0}"                    # 1 = push branch + open PR (needs gh auth)

log() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

guard_api_key() {
  if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    log "FATAL: ANTHROPIC_API_KEY is set; refusing to run (would bill metered API)."
    exit 1
  fi
}

usage_snapshot() {
  npx -y ccusage@latest blocks --active --json 2>/dev/null \
    | jq -c '.blocks[0] // {}' 2>/dev/null || echo '{}'
}

next_task() {  # prints "LINENO|repo|description" of the first unchecked task
  grep -nE '^- \[ \] ' "$WORKLIST" | head -1 | \
    sed -E 's/^([0-9]+):- \[ \] ([^:]+): (.*)$/\1|\2|\3/'
}

check_off() {  # mark line $1 done
  sed -i "${1}s/^- \[ \]/- [x]/" "$WORKLIST"
}

run_one() {
  guard_api_key
  local task line repo desc
  task="$(next_task)" || true
  if [ -z "$task" ]; then log "worklist empty — nothing to do"; return 2; fi
  line="${task%%|*}"; rest="${task#*|}"; repo="${rest%%|*}"; desc="${rest#*|}"
  local dir="$ROOT/$repo"
  if [ ! -d "$dir/.git" ]; then log "repo '$repo' not cloned in $ROOT — skipping"; check_off "$line"; return 0; fi

  log "snapshot: $(usage_snapshot)"
  log "START [$repo] $desc"
  cd "$dir"
  git fetch -q origin && git checkout -q main && git pull -q --rebase || true
  local branch="agent/$(date -u +%Y%m%d-%H%M%S)"
  git checkout -q -b "$branch"

  local prompt="You are running unattended on a server. Repo: $repo.
Task: $desc
Rules: make the smallest change that satisfies the task; do not refactor unrelated
code; work only in this repo; if the task is ambiguous or needs a human decision,
make NO changes and instead write a short note explaining why. When done, ensure
the change builds/lints if a quick check exists."

  if claude -p "$prompt" --dangerously-skip-permissions >>"$LOG" 2>&1; then
    if git diff --quiet && git diff --cached --quiet; then
      log "no changes produced for [$repo] $desc — leaving task unchecked, moving on"
      git checkout -q main; git branch -qD "$branch" || true
      return 0
    fi
    git add -A
    git -c user.name="maxmoneycash-agent" -c user.email="agent@maxmoneycash" \
        commit -q -m "agent: $desc"
    if [ "$PUSH" = "1" ]; then
      git push -q -u origin "$branch" && command -v gh >/dev/null && \
        gh pr create --fill --head "$branch" >>"$LOG" 2>&1 || log "push/PR skipped (auth?)"
    fi
    check_off "$line"
    log "DONE  [$repo] $desc  (branch $branch, pushed=$PUSH)"
    git checkout -q main
    return 0
  else
    log "FAIL/CAP [$repo] $desc — backing off ${BACKOFF}s (likely usage limit or error)"
    git checkout -q main; git branch -qD "$branch" || true
    return 1
  fi
}

loop() {
  log "paced runner started (WAVE_GAP=${WAVE_GAP}s BACKOFF=${BACKOFF}s PUSH=${PUSH})"
  while true; do
    set +e; run_one; rc=$?; set -e
    case "$rc" in
      0) sleep "$WAVE_GAP" ;;        # success — short gap, next task
      1) sleep "$BACKOFF" ;;         # fail/cap — long back off, then retry
      2) sleep 3600 ;;               # empty worklist — idle an hour
    esac
  done
}

install_service() {
  guard_api_key
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/agent-runner.service" <<EOF
[Unit]
Description=maxmoneycash paced overnight agent runner
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/env bash $HERE/paced-runner.sh
Restart=always
RestartSec=30
Environment=PUSH=$PUSH

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now agent-runner.service
  sudo loginctl enable-linger "$USER" 2>/dev/null || true  # survive logout/reboot
  log "installed + started systemd --user service 'agent-runner'"
  echo "Watch it:  journalctl --user -u agent-runner -f   (or tail -f $LOG)"
}

case "${1:-}" in
  --install) install_service ;;
  --once)    guard_api_key; run_one ;;
  *)         loop ;;
esac
