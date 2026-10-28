#!/usr/bin/env bash
# Publish collected artifacts without disturbing other Git operations.
set -euo pipefail
REPO_DIR="${1:?repository path required}"
shift
lock_held=false
check_only=false
for argument in "$@"; do
  case "$argument" in
    --lock-held) lock_held=true ;;
    --check-git-idle) check_only=true ;;
    *) echo "unknown publication option: $argument" >&2; exit 2 ;;
  esac
done
cd "$REPO_DIR"
if [ "$lock_held" = false ]; then
  exec 9>"$(git rev-parse --git-path tokenstats.flock)"
  if ! lockf -s -t 0 9; then
    echo "collector is active; not publishing"
    exit 0
  fi
fi
log() { echo "[$(date -u +%H:%M:%S)] $*"; }

ensure_git_idle() {
  local state path unmerged
  for state in index.lock rebase-merge rebase-apply MERGE_HEAD SQUASH_MSG CHERRY_PICK_HEAD REVERT_HEAD; do
    path="$(git rev-parse --git-path "$state")"
    if [ -e "$path" ]; then
      log "ERROR: Git state $state exists; leaving it untouched and deferring publication"
      return 1
    fi
  done
  if ! unmerged="$(git ls-files --unmerged)"; then
    log "ERROR: could not inspect unresolved index entries; preserving Git state"
    return 1
  fi
  if [ -n "$unmerged" ]; then
    log "ERROR: unresolved index entries exist; leaving them untouched and deferring publication"
    return 1
  fi
}
ensure_git_idle
if [ "$check_only" = true ]; then exit 0; fi
# A collector commit must never include, unstage or stash somebody's staged
# source edits. Keep collected data on disk and retry after their Git work.
if git diff --cached --quiet -- . \
  ':(exclude)data/tokens.json' ':(exclude)data/cursor-cache.json' \
  ':(exclude)data/grok-cache.json' ':(exclude)data/hermes-cache.json'; then
  :
else
  staged_status=$?
  if [ "$staged_status" -ne 1 ]; then
    log "ERROR: could not inspect staged changes; leaving Git state untouched"
    exit "$staged_status"
  fi
  log "unrelated staged changes exist; leaving the index untouched and deferring publication"
  exit 0
fi
git add data/tokens.json data/cursor-cache.json data/grok-cache.json data/hermes-cache.json
if git diff --cached --quiet -- data/tokens.json data/cursor-cache.json data/grok-cache.json data/hermes-cache.json; then
  log "tokens.json unchanged; checking for unpublished commits"
else
  git commit -q --only -m "chore: token stats $(date -u +%Y-%m-%dT%H:%MZ)" -- data/tokens.json data/cursor-cache.json data/grok-cache.json data/hermes-cache.json
fi

# Real-time cadence with noise guard: push immediately on meaningful token
# burn, but batch tiny changes. Compare with the last published ledger, never
# the preceding local commit: small scans accumulate and become due once the
# published ledger reaches the age limit. Failed pushes stay eligible.
THRESHOLD=${TOKENSTATS_PUSH_THRESHOLD:-25000000}
MAX_AGE_SEC=${TOKENSTATS_MAX_AGE_SEC:-3600}
if PUBLICATION=$(python3 "$REPO_DIR/scripts/publication_checkpoint.py" \
  --repo "$REPO_DIR" --threshold "$THRESHOLD" --max-age "$MAX_AGE_SEC"); then
  log "$PUBLICATION"
else
  publication_status=$?
  log "$PUBLICATION"
  if [ "$publication_status" -eq 3 ]; then
    exit 0
  fi
  exit "$publication_status"
fi

# Fetch/push failures do not own a rebase or a Git lock. Only abort after our
# own rebase command failed, and never unlink Git state files to force a retry.
for i in 1 2 3 4 5; do
  if git fetch -q origin main; then
    ensure_git_idle
    if git rebase -X theirs --autostash origin/main; then
      if git push -q origin main; then
        log "pushed token stats"
        exit 0
      fi
    else
      if ! git rebase --abort; then
        log "ERROR: collector rebase failed without a recoverable rebase; preserving Git state"
        exit 1
      fi
    fi
  fi
  sleep 5
done
log "failed to push after 5 attempts"
exit 1
