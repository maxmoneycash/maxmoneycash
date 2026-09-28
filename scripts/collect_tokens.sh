#!/bin/bash
# Collects AI-agent token usage from this Mac + the cloud agent-host, merges
# them, builds data/tokens.json, and pushes so GitHub Actions re-renders the
# README cards. Safe to run often (hourly):
#   - single-run LOCK (two runs can never race the git push)
#   - complete snapshot and monotonic guards; failures keep the last-good file
#   - skips when nothing changed (no empty commits on idle hours)
#   - push survives a dirty tree + interleaving Action commits (autostash + rebase)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# turbotokens is the counter. It is CLI-compatible with ccusage for every
# invocation below, ~19x faster end to end on this dataset (2m23s vs 45m+), and
# — the reason for the switch — it does not double-count Codex's re-emitted
# token_count events. Measured: ccusage over-reports Codex by 10,159,852,651
# tokens, within 21,530 of what codex_true_usage.py independently computes as
# the correction. ccusage remains the fallback so a missing binary degrades
# rather than fails.
#
# --bun forces the bun runtime for the fallback: /usr/local/bin/node is an
# x86_64 leftover and the ccusage wrapper otherwise spawns it and looks for the
# wrong native binary.
if [ -z "${CCUSAGE:-}" ]; then
  for candidate in "$HOME/.local/bin/turbotokens" /usr/local/bin/turbotokens /opt/homebrew/bin/turbotokens; do
    if [ -x "$candidate" ]; then CCUSAGE="$candidate"; break; fi
  done
fi
CCUSAGE="${CCUSAGE:-bunx --bun ccusage@20.0.9}"
case "$CCUSAGE" in *turbotokens*) COUNTER_IS_TURBOTOKENS=1 ;; *) COUNTER_IS_TURBOTOKENS=0 ;; esac
export PATH="$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
# launchd does not set TMPDIR, so scanner runs fell back to a different, cold
# parse cache than interactive shells (turbotokens keeps its cache in TMPDIR).
# Pin it to the real per-user temp dir so every context shares one warm cache.
export TMPDIR="${TMPDIR:-$(getconf DARWIN_USER_TEMP_DIR)}"
cd "$REPO_DIR"

# Bound every scanner invocation. A failed or timed-out scan aborts
# publication and leaves the last-good ledger and original timestamp intact.
if command -v timeout >/dev/null 2>&1; then
  SCAN_TIMEOUT="timeout 300"
elif command -v gtimeout >/dev/null 2>&1; then
  SCAN_TIMEOUT="gtimeout 300"
else
  SCAN_TIMEOUT=""
fi

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# --- single-run lock: never let two collections overlap (they'd race git) ---
# `lockf` holds an OS-level exclusive lock on fd 9 for this shell's lifetime.
# Unlike an age-based directory takeover, it cannot steal or unlink another
# live process's lock. `-k` keeps the inert file so concurrent open/unlock
# ordering stays well-defined.
LOCK_FILE="$(git rev-parse --git-path tokenstats.flock)"
exec 9>"$LOCK_FILE"
if ! lockf -s -t 0 9; then
  log "another run is still alive; skipping"; exit 0
fi

# One-time compatibility with the directory lock used by older revisions.
# A pre-upgrade collector that is still alive wins; a fresh ambiguous lock
# fails closed; only an old lock with no live owner is removed. All new
# revisions are already serialized above, so they cannot race this migration.
LEGACY_LOCK="$(git rev-parse --git-path tokenstats.lock)"
if [ -d "$LEGACY_LOCK" ]; then
  OWNER_PID=""
  if [ -f "$LEGACY_LOCK/pid" ]; then
    read -r OWNER_PID < "$LEGACY_LOCK/pid" || OWNER_PID=""
  fi
  if [[ "$OWNER_PID" =~ ^[0-9]+$ ]] && kill -0 "$OWNER_PID" 2>/dev/null; then
    log "pre-upgrade run is still alive (pid $OWNER_PID); skipping"; exit 0
  fi
  if [ -z "$(find "$LEGACY_LOCK" -maxdepth 0 -mmin +15 2>/dev/null)" ]; then
    log "pre-upgrade lock is fresh; skipping"; exit 0
  fi
  log "removing stale pre-upgrade lock (>15m)"
  rm -rf "$LEGACY_LOCK"
fi
# Ordinary collection never performs authoritative server reconciliation.
# Any real correction is a separate manually reviewed procedure with matching
# source evidence and an explicit snapshot boundary, including new live work.

TMP=$(mktemp -d)
LOCAL="$TMP/local"
CLOUD="$TMP/cloud"
MERGED="$TMP/merged"
mkdir -p "$LOCAL" "$CLOUD" "$MERGED"
trap 'rm -rf "$TMP"' EXIT

# --- collect local ccusage sources SEQUENTIALLY. Parallel bunx/ccusage invocations
#     race on the package cache and produced empty/partial JSON (the root cause
#     of the 2026-06-21/22 collection failures). Each required scan's status is
#     checked before proceeding; no background failure becomes an empty source.
SCAN_LOG="$HOME/Library/Logs/tokenstats-scan.log"
: > "$SCAN_LOG"
collect_required() {
  local label="$1" output="$2"
  shift 2
  if "$@" > "$output" 2>>"$SCAN_LOG" && [ -s "$output" ]; then
    return 0
  fi
  log "ERROR: $label collection failed/incomplete — keeping previous tokens.json and its original timestamp; retry collection"
  return 1
}
log "collecting local ccusage…"
collect_required "local monthly" "$LOCAL/monthly.json" $SCAN_TIMEOUT $CCUSAGE monthly --json --offline --timezone UTC
collect_required "local daily" "$LOCAL/daily.json" $SCAN_TIMEOUT $CCUSAGE daily --json --offline --timezone UTC --since "$(date -u -v-35d +%Y-%m-%d)"
for agent in claude codex droid kimi opencode; do
  collect_required "local $agent" "$LOCAL/agent-$agent.json" $SCAN_TIMEOUT $CCUSAGE "$agent" monthly --json --offline --breakdown --timezone UTC
done

log "collecting local true counters…"
if [ "$COUNTER_IS_TURBOTOKENS" = "1" ]; then
  # Same counter and scope: freeze the outputs already captured above. A
  # second scan can grow between the subtraction and addition operands.
  cp "$LOCAL/agent-codex.json" "$LOCAL/codex-true.json"
  cp "$LOCAL/agent-kimi.json" "$LOCAL/kimi-true.json"
else
  collect_required "local Codex correction" "$LOCAL/codex-true.json" $SCAN_TIMEOUT python3 "$REPO_DIR/scripts/codex_true_usage.py"
  collect_required "local Kimi correction" "$LOCAL/kimi-true.json" $SCAN_TIMEOUT python3 "$REPO_DIR/scripts/kimi_true_usage.py"
fi
collect_required "local Grok" "$LOCAL/grok-true.json" $SCAN_TIMEOUT python3 "$REPO_DIR/scripts/grok_true_usage.py"
# Failed dashboard input keeps the entire last-good publication. Reusing a
# cached slice must not label missing input as a fresh complete collection.
collect_required "Cursor dashboard" "$LOCAL/cursor.json" $SCAN_TIMEOUT python3 "$REPO_DIR/scripts/cursor_usage.py"
python3 "$REPO_DIR/scripts/token_publication_guards.py" inputs "$LOCAL"
log "local collected"

# Cloud is part of the established source scope. It cannot be dropped even
# when local growth would conceal its missing tokens.
if bash "$REPO_DIR/scripts/collect_cloud_tokens.sh" "$CLOUD" >>"$TMP/cloud.log" 2>&1; then
  python3 "$REPO_DIR/scripts/token_publication_guards.py" inputs "$CLOUD"
  log "cloud collected"
  SOURCES=("$LOCAL" "$CLOUD")
else
  log "ERROR: cloud collection failed/incomplete — keeping previous tokens.json and its original timestamp; retry collection"
  exit 1
fi

# --- merge local + cloud sources into a single combined input directory
if [ ${#SOURCES[@]} -eq 2 ]; then
  python3 "$REPO_DIR/scripts/merge_token_sources.py" "$MERGED" "local:${SOURCES[0]}" "cloud:${SOURCES[1]}"
else
  python3 "$REPO_DIR/scripts/merge_token_sources.py" "$MERGED" "local:${SOURCES[0]}"
fi

# --- safety: ccusage monthly is the backbone; if it came back empty/invalid,
#     abort rather than build (and push) a near-empty tokens.json ---
if ! python3 -c "import json,sys; d=json.load(open('$MERGED/monthly.json')); sys.exit(0 if d.get('monthly') else 1)" 2>/dev/null; then
  log "ERROR: merged monthly empty/invalid — aborting, keeping previous tokens.json"; exit 1
fi

# Atomic write so a failed build can never truncate data/tokens.json.
# data/cloud-baseline.json = frozen usage of the old agent box (its raw logs
# were destroyed in the 2026-07-05 hermes rebuild) — added on top of what the
# live logs still prove. See scripts/make_cloud_baseline.py.
python3 "$REPO_DIR/scripts/build_tokens_json.py" "$MERGED" "$REPO_DIR/data/cloud-baseline.json" > "$TMP/tokens.out"

# BEGIN ordinary publication gate
# No percentage, accounting revision, or correction flag authorizes a loss.
# Check every retained source/month, so growth elsewhere cannot conceal it.
python3 "$REPO_DIR/scripts/token_publication_guards.py" publication "$TMP/tokens.out" "$REPO_DIR/data/tokens.json"
OLD=$(python3 -c "import json;print(json.load(open('data/tokens.json'))['totals']['totalTokens'])" 2>/dev/null || echo 0)
OLD_TIME=$(python3 -c "import json;print(json.load(open('data/tokens.json'))['generated_at'])" 2>/dev/null || echo "")
NEW=$(python3 -c "import json;print(json.load(open('$TMP/tokens.out'))['totals']['totalTokens'])")
mv "$TMP/tokens.out" data/tokens.json
# END ordinary publication gate
# Promote the dashboard cache only with the accepted complete publication.
cp "$LOCAL/cursor.json" "$REPO_DIR/data/cursor-cache.json"

if [ "${TOKENSTATS_NO_GIT:-0}" = "1" ]; then
  log "audit mode: rebuilt token artifacts without committing or pushing"
  exit 0
fi


git add data/tokens.json data/cursor-cache.json data/grok-cache.json data/hermes-cache.json
if git diff --cached --quiet; then
  log "tokens.json unchanged; nothing to push"
  exit 0
fi
git commit -q -m "chore: token stats $(date -u +%Y-%m-%dT%H:%MZ)"

# Real-time cadence with noise guard: push immediately on meaningful token
# burn, but batch tiny changes so we don't spam commits every 15 minutes.
THRESHOLD=${TOKENSTATS_PUSH_THRESHOLD:-25000000}
MAX_AGE_SEC=${TOKENSTATS_MAX_AGE_SEC:-3600}
DELTA=$((NEW - OLD))
FORCE_AGE=false
if [ -n "$OLD_TIME" ]; then
  OLD_EPOCH=$(date -j -u -f "%Y-%m-%dT%H:%M:%S" "${OLD_TIME%%Z}" "+%s" 2>/dev/null || echo 0)
  NOW_EPOCH=$(date -u +%s)
  AGE=$((NOW_EPOCH - OLD_EPOCH))
  if [ "$AGE" -ge "$MAX_AGE_SEC" ]; then
    FORCE_AGE=true
  fi
fi
if [ "$DELTA" -lt "$THRESHOLD" ] && [ "$FORCE_AGE" = false ]; then
  log "delta ${DELTA} < ${THRESHOLD}; committing locally, skipping push"
  exit 0
fi
if [ "$FORCE_AGE" = true ]; then
  log "age ${AGE}s >= ${MAX_AGE_SEC}s; forcing push"
else
  log "delta ${DELTA} >= ${THRESHOLD}; pushing"
fi

# The readme/3d workflows also commit to main. Rebase our generated-data commit
# onto theirs, preferring OUR data on conflict (it's the freshest), and ALWAYS
# abort a failed rebase so a half-finished rebase can never wedge every future
# run — that left-behind .git/rebase-merge froze pushes for days in June 2026.
# --autostash stashes any unrelated WIP in the working tree (e.g. uncommitted
# scripts/agent-host/ edits) so a dirty tree can't block the push either.
clear_rebase() {
  git rebase --abort 2>/dev/null || true
  rm -rf .git/rebase-merge .git/rebase-apply 2>/dev/null || true
  # A git process that crashed mid-commit leaves .git/index.lock behind, which
  # then makes EVERY future run die with "Unable to create index.lock". Our
  # single-run tokenstats.lock guarantees no other collector is running, so any
  # leftover index.lock here is stale by definition — froze the push for 72h in
  # June 2026 until it was cleared by hand.
  rm -f .git/index.lock 2>/dev/null || true
}
clear_rebase  # heal any pre-existing stuck rebase/lock before we start
for i in 1 2 3 4 5; do
  if git fetch -q origin main \
     && git rebase -X theirs --autostash origin/main \
     && git push -q origin main; then
    log "pushed token stats"
    exit 0
  fi
  clear_rebase
  sleep 5
done
log "failed to push after 5 attempts"
exit 1
