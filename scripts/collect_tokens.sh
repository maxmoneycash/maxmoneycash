#!/bin/bash
# Collects AI-agent token usage from this Mac + the cloud agent-host, merges
# them, builds data/tokens.json, and pushes so GitHub Actions re-renders the
# README cards. Safe to run often (hourly):
#   - single-run LOCK (two runs can never race the git push)
#   - monotonic GUARD (a transient glitch can't push near-empty stats)
#   - skips when nothing changed (no empty commits on idle hours)
#   - push survives a dirty tree + interleaving Action commits (autostash + rebase)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# --bun forces the bun runtime: /usr/local/bin/node is an x86_64 leftover and
# the ccusage wrapper otherwise spawns it and looks for the wrong native binary.
CCUSAGE="${CCUSAGE:-bunx --bun ccusage@20.0.9}"
export PATH="$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$REPO_DIR"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# --- single-run lock: never let two collections overlap (they'd race git) ---
LOCK="$REPO_DIR/.git/tokenstats.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +15 2>/dev/null)" ]; then
    log "stale lock (>15m); reclaiming"; rm -rf "$LOCK"; mkdir "$LOCK"
  else
    log "another run in progress; skipping"; exit 0
  fi
fi
TMP=$(mktemp -d)
LOCAL="$TMP/local"
CLOUD="$TMP/cloud"
MERGED="$TMP/merged"
mkdir -p "$LOCAL" "$CLOUD" "$MERGED"
trap 'rm -rf "$LOCK" "$TMP"' EXIT

# --- collect local ccusage sources SEQUENTIALLY. Parallel bunx/ccusage invocations
#     race on the package cache and produced empty/partial JSON (the root cause
#     of the 2026-06-21/22 collection failures). The python true counters can
#     still run in parallel because they don't touch bunx.
log "collecting local ccusage…"
$CCUSAGE monthly --json --offline --timezone UTC > "$LOCAL/monthly.json" 2>/dev/null \
    || echo '{"monthly":[]}' > "$LOCAL/monthly.json"
$CCUSAGE daily --json --offline --timezone UTC --since "$(date -u -v-35d +%Y-%m-%d)" > "$LOCAL/daily.json" 2>/dev/null \
    || echo '{"daily":[]}' > "$LOCAL/daily.json"
for agent in claude codex droid kimi opencode; do
  $CCUSAGE "$agent" monthly --json --offline --breakdown > "$LOCAL/agent-$agent.json" 2>/dev/null \
      || echo '{"monthly":[],"totals":{}}' > "$LOCAL/agent-$agent.json"
done

log "collecting local true counters…"
( python3 "$REPO_DIR/scripts/codex_true_usage.py" > "$LOCAL/codex-true.json" 2>/dev/null \
    || echo '{"totals":{},"monthly":[]}' > "$LOCAL/codex-true.json" ) &
( python3 "$REPO_DIR/scripts/kimi_true_usage.py" > "$LOCAL/kimi-true.json" 2>/dev/null \
    || echo '{"totals":{},"monthly":[]}' > "$LOCAL/kimi-true.json" ) &
( python3 "$REPO_DIR/scripts/grok_true_usage.py" > "$LOCAL/grok-true.json" 2>/dev/null \
    || echo '{"totals":{},"monthly":[]}' > "$LOCAL/grok-true.json" ) &
# Cursor dashboard (network); fall back to the committed cache on any failure
( if python3 "$REPO_DIR/scripts/cursor_usage.py" > "$LOCAL/cursor.json" 2>/dev/null && [ -s "$LOCAL/cursor.json" ]; then
    cp "$LOCAL/cursor.json" "$REPO_DIR/data/cursor-cache.json"
  elif [ -f "$REPO_DIR/data/cursor-cache.json" ]; then
    cp "$REPO_DIR/data/cursor-cache.json" "$LOCAL/cursor.json"
  else echo '{"totals":{},"monthly":[]}' > "$LOCAL/cursor.json"; fi ) &
wait
log "local collected"

# --- collect from the cloud agent-host. Best-effort: if the box is offline or
#     unreachable, we still publish the local stats.
if bash "$REPO_DIR/scripts/collect_cloud_tokens.sh" "$CLOUD" >>"$TMP/cloud.log" 2>&1; then
  log "cloud collected"
  SOURCES=("$LOCAL" "$CLOUD")
else
  log "WARNING: cloud collection failed (see $TMP/cloud.log); using local only"
  SOURCES=("$LOCAL")
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

# --- safety: all-time totals only ever grow; a drop = a collection glitch.
#     Refuse to overwrite good data with a >2% regression. ---
OLD=$(python3 -c "import json;print(json.load(open('data/tokens.json'))['totals']['totalTokens'])" 2>/dev/null || echo 0)
OLD_TIME=$(python3 -c "import json;print(json.load(open('data/tokens.json'))['generated_at'])" 2>/dev/null || echo "")
NEW=$(python3 -c "import json;print(json.load(open('$TMP/tokens.out'))['totals']['totalTokens'])")
if [ "$NEW" -lt "$((OLD * 98 / 100))" ]; then
  log "ERROR: new total $NEW < 98% of old $OLD — glitch, keeping previous tokens.json"; exit 1
fi
mv "$TMP/tokens.out" data/tokens.json

git add data/tokens.json data/cursor-cache.json data/grok-cache.json
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
