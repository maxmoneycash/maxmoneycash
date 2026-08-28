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
export PATH="$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
# launchd does not set TMPDIR, so scanner runs fell back to a different, cold
# parse cache than interactive shells (turbotokens keeps its cache in TMPDIR).
# Pin it to the real per-user temp dir so every context shares one warm cache.
export TMPDIR="${TMPDIR:-$(getconf DARWIN_USER_TEMP_DIR)}"
cd "$REPO_DIR"

# Hard deadline on every scanner invocation. A scan that used to take seconds
# wedged for 8 hours on 2026-08-27 (turbotokens codex spinning on a live
# session file) and froze the whole pipeline — including the server drift
# check, whose entire job is to not be down for days. A timed-out scan falls
# through to each call's empty-JSON fallback; the monotonic guards below keep
# a partial scan from ever shrinking the published ledger.
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
# Server drift check FIRST, before any scanning. It compares the committed
# ledger against the public total and re-anchors on >2% drift (observed:
# restart-burst minting took the server from 68.2B to 270.7B in three days).
# It must not wait behind the scans: a hung or aborted scan cycle would take
# the drift protection down with it, which is exactly when it is needed.
RECONCILE_LOG="$HOME/Library/Logs/tokenstats-reconcile.log"
python3 "$REPO_DIR/scripts/reconcile_server.py" >> "$RECONCILE_LOG" 2>&1 \
  && log "server drift check ok" \
  || log "WARNING: server drift check failed (see $RECONCILE_LOG)"

TMP=$(mktemp -d)
LOCAL="$TMP/local"
CLOUD="$TMP/cloud"
MERGED="$TMP/merged"
mkdir -p "$LOCAL" "$CLOUD" "$MERGED"
trap 'rm -rf "$TMP"' EXIT

# --- collect local ccusage sources SEQUENTIALLY. Parallel bunx/ccusage invocations
#     race on the package cache and produced empty/partial JSON (the root cause
#     of the 2026-06-21/22 collection failures). The python true counters can
#     still run in parallel because they don't touch bunx.
log "collecting local ccusage…"
$SCAN_TIMEOUT $CCUSAGE monthly --json --offline --timezone UTC > "$LOCAL/monthly.json" 2>/dev/null \
    || echo '{"monthly":[]}' > "$LOCAL/monthly.json"
$SCAN_TIMEOUT $CCUSAGE daily --json --offline --timezone UTC --since "$(date -u -v-35d +%Y-%m-%d)" > "$LOCAL/daily.json" 2>/dev/null \
    || echo '{"daily":[]}' > "$LOCAL/daily.json"
for agent in claude codex droid kimi opencode; do
  $SCAN_TIMEOUT $CCUSAGE "$agent" monthly --json --offline --breakdown > "$LOCAL/agent-$agent.json" 2>/dev/null \
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
  # Keep hermes history alive from the committed cache so the box being
  # offline can't shrink the totals (hermes-true must exist in exactly ONE
  # source dir — merge sums same-named files across sources).
  python3 "$REPO_DIR/scripts/hermes_true_usage.py" > "$LOCAL/hermes-true.json" 2>/dev/null \
      || echo '{"totals":{},"monthly":[]}' > "$LOCAL/hermes-true.json"
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

# --- safety: all-time totals normally only grow; a drop = a collection glitch.
#     The one exception is the first audited Codex cumulative-delta correction,
#     which intentionally removes duplicated token_count events. ---
OLD=$(python3 -c "import json;print(json.load(open('data/tokens.json'))['totals']['totalTokens'])" 2>/dev/null || echo 0)
OLD_TIME=$(python3 -c "import json;print(json.load(open('data/tokens.json'))['generated_at'])" 2>/dev/null || echo "")
NEW=$(python3 -c "import json;print(json.load(open('$TMP/tokens.out'))['totals']['totalTokens'])")
OLD_CODEX_CORRECTED=$(python3 -c "import json;print('1' if json.load(open('data/tokens.json')).get('corrections',{}).get('codexCumulativeAdjusted') else '0')" 2>/dev/null || echo 0)
NEW_CODEX_CORRECTED=$(python3 -c "import json;print('1' if json.load(open('$TMP/tokens.out')).get('corrections',{}).get('codexCumulativeAdjusted') else '0')")
OLD_SOURCES=$(python3 -c "import json;print(','.join(sorted(x['label'] for x in json.load(open('data/tokens.json')).get('sources',[]))))" 2>/dev/null || echo "")
NEW_SOURCES=$(python3 -c "import json;print(','.join(sorted(x['label'] for x in json.load(open('$TMP/tokens.out')).get('sources',[]))))")
if [ "$NEW" -lt "$((OLD * 98 / 100))" ] && ! { [ "$OLD_CODEX_CORRECTED" = 0 ] && [ "$NEW_CODEX_CORRECTED" = 1 ] && [ "$OLD_SOURCES" = "$NEW_SOURCES" ]; }; then
  log "ERROR: new total $NEW < 98% of old $OLD — glitch, keeping previous tokens.json"; exit 1
fi
if [ "$NEW" -lt "$OLD" ]; then
  log "audited correction: removing $((OLD - NEW)) duplicated Codex tokens"
fi
mv "$TMP/tokens.out" data/tokens.json

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
