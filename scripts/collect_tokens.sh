#!/bin/bash
# Collects AI-agent token usage via ccusage -> data/tokens.json, then commits &
# pushes so the GitHub Action re-renders the README cards. Runs locally (the
# usage logs only exist on this machine) and is safe to run often (hourly):
#   - PARALLEL collection (fast: all sources run at once, not one-by-one)
#   - single-run LOCK (safe: two runs can never race the git push)
#   - monotonic GUARD (safe: a transient glitch can't push near-empty stats)
#   - skips when nothing changed (clean: no empty commits on idle hours)
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
trap 'rm -rf "$LOCK" "$TMP"' EXIT

# --- collect ccusage sources SEQUENTIALLY. Parallel bunx/ccusage invocations
#     race on the package cache and produced empty/partial JSON (the root cause
#     of the 2026-06-21/22 collection failures). The python true counters can
#     still run in parallel because they don't touch bunx.
log "collecting ccusage…"
$CCUSAGE monthly --json --offline --timezone UTC > "$TMP/monthly.json" 2>/dev/null \
    || echo '{"monthly":[]}' > "$TMP/monthly.json"
$CCUSAGE daily --json --offline --timezone UTC --since "$(date -u -v-35d +%Y-%m-%d)" > "$TMP/daily.json" 2>/dev/null \
    || echo '{"daily":[]}' > "$TMP/daily.json"
for agent in claude codex droid kimi opencode; do
  $CCUSAGE "$agent" monthly --json --offline --breakdown > "$TMP/agent-$agent.json" 2>/dev/null \
      || echo '{"monthly":[],"totals":{}}' > "$TMP/agent-$agent.json"
done

log "collecting true counters…"
( python3 "$REPO_DIR/scripts/codex_true_usage.py" > "$TMP/codex-true.json" 2>/dev/null \
    || echo '{"totals":{},"monthly":[]}' > "$TMP/codex-true.json" ) &
( python3 "$REPO_DIR/scripts/kimi_true_usage.py" > "$TMP/kimi-true.json" 2>/dev/null \
    || echo '{"totals":{},"monthly":[]}' > "$TMP/kimi-true.json" ) &
( python3 "$REPO_DIR/scripts/grok_true_usage.py" > "$TMP/grok-true.json" 2>/dev/null \
    || echo '{"totals":{},"monthly":[]}' > "$TMP/grok-true.json" ) &
# Cursor dashboard (network); fall back to the committed cache on any failure
( if python3 "$REPO_DIR/scripts/cursor_usage.py" > "$TMP/cursor.json" 2>/dev/null && [ -s "$TMP/cursor.json" ]; then
    cp "$TMP/cursor.json" "$REPO_DIR/data/cursor-cache.json"
  elif [ -f "$REPO_DIR/data/cursor-cache.json" ]; then
    cp "$REPO_DIR/data/cursor-cache.json" "$TMP/cursor.json"
  else echo '{"totals":{},"monthly":[]}' > "$TMP/cursor.json"; fi ) &
wait
log "collected"

# --- safety: ccusage monthly is the backbone; if it came back empty/invalid,
#     abort rather than build (and push) a near-empty tokens.json ---
if ! python3 -c "import json,sys; d=json.load(open('$TMP/monthly.json')); sys.exit(0 if d.get('monthly') else 1)" 2>/dev/null; then
  log "ERROR: ccusage monthly empty/invalid — aborting, keeping previous tokens.json"; exit 1
fi

# Atomic write so a failed build can never truncate data/tokens.json
python3 "$REPO_DIR/scripts/build_tokens_json.py" "$TMP" > "$TMP/tokens.out"

# --- safety: all-time totals only ever grow; a drop = a collection glitch.
#     Refuse to overwrite good data with a >2% regression. ---
OLD=$(python3 -c "import json;print(json.load(open('data/tokens.json'))['totals']['totalTokens'])" 2>/dev/null || echo 0)
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

# The readme/3d workflows also commit to main. Rebase our generated-data commit
# onto theirs, preferring OUR data on conflict (it's the freshest), and ALWAYS
# abort a failed rebase so a half-finished rebase can never wedge every future
# run — that left-behind .git/rebase-merge froze pushes for days in June 2026.
# --autostash stashes any unrelated WIP in the working tree (e.g. uncommitted
# scripts/agent-host/ edits) so a dirty tree can't block the push either.
clear_rebase() {
  git rebase --abort 2>/dev/null || true
  rm -rf .git/rebase-merge .git/rebase-apply 2>/dev/null || true
}
clear_rebase  # heal any pre-existing stuck rebase before we start
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
