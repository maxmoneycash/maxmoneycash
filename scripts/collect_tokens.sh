#!/bin/bash
# Collects AI-agent token usage from this Mac + the cloud agent-host, merges
# them, builds data/tokens.json, and pushes so GitHub Actions re-renders the
# README cards. Safe to run often (hourly):
#   - single-run LOCK (two runs can never race the git push)
#   - monotonic GUARD (a transient glitch can't push near-empty stats)
#   - skips when nothing changed (no empty commits on idle hours)
#   - push survives a dirty tree + interleaving Action commits (autostash + rebase)
set -euo pipefail

CALLER_PWD="$(pwd -P)"
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

# Hard deadline on every scanner invocation. A scan that used to take seconds
# wedged for 8 hours on 2026-08-27 (turbotokens codex spinning on a live
# session file) and froze the whole pipeline — including the server drift
# check, whose entire job is to not be down for days. A timed-out scan falls
# through to each call's empty-JSON fallback; the monotonic guards below keep
# a partial scan from ever shrinking the published ledger.
# 900 s, not 300: on 2026-10-20 (load average ~330 from other work) the monthly
# scan overran 300 s on every cycle from 17:48Z, so nothing published for hours
# and the drift check refused the stale ledger; a 900 s run finished every scan
# in under 3 minutes. Still a hard bound on a wedged scan.
SCAN_TIMEOUT_SEC="${TOKENSTATS_SCAN_TIMEOUT:-900}"
if command -v timeout >/dev/null 2>&1; then
  SCAN_TIMEOUT="timeout $SCAN_TIMEOUT_SEC"
elif command -v gtimeout >/dev/null 2>&1; then
  SCAN_TIMEOUT="gtimeout $SCAN_TIMEOUT_SEC"
else
  SCAN_TIMEOUT=""
fi

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# --- sandboxed audit run ------------------------------------------------------
# TOKENSTATS_AUDIT_DIR=<dir> rebuilds the ledger without touching anything that
# is published: the built ledger goes to <dir>/tokens.json (data/tokens.json is
# only read, as the guard's reference), scan logs go to <dir>/, the side caches
# (grok/hermes/cursor) are copied to <dir>/cache/ and updated there
# (TOKENSTATS_CACHE_DIR), the server drift check is skipped, and nothing is
# committed or pushed. <dir> must be outside every checkout of this repository:
# a relative path resolves against the caller's directory, and a dir inside a
# checkout (e.g. "data", any spelling of it) is refused by
# scripts/audit_dir_guard.py, since writing tokens.json there with a fresh
# generated_at would hand the next live reconcile a ledger it trusts.
# Unlike TOKENSTATS_NO_GIT (which still replaces data/tokens.json), this is
# safe on the live checkout.
#   TOKENSTATS_OFFLINE=1           no network: Cursor from its cached rows,
#                                  cloud box skipped (Hermes from its cache)
#   TOKENSTATS_STRICT_SCANS=1      abort before building if any scan failed or
#                                  timed out (a partial scan must never be
#                                  frozen into a baseline; make_purge_baseline.py)
#   TOKENSTATS_PURGE_BASELINE=none build without data/local-purge-baseline.json
#   TOKENSTATS_SCAN_TIMEOUT=<sec>  per-scan deadline (default 900)
AUDIT_DIR="${TOKENSTATS_AUDIT_DIR:-}"
OFFLINE="${TOKENSTATS_OFFLINE:-0}"
STRICT_SCANS="${TOKENSTATS_STRICT_SCANS:-0}"
if [ -n "$AUDIT_DIR" ]; then
  case "$AUDIT_DIR" in /*) ;; *) AUDIT_DIR="$CALLER_PWD/$AUDIT_DIR" ;; esac
  # Compared by directory identity (device + inode), not spelling: the disk is
  # case-insensitive, so ~/MAXMONEYCASH/data is the live data/. Fails closed.
  if ! GUARD_OUT="$(python3 "$REPO_DIR/scripts/audit_dir_guard.py" "$AUDIT_DIR" "$REPO_DIR")"; then
    log "ERROR: TOKENSTATS_AUDIT_DIR is inside a checkout of this repository: ${GUARD_OUT#REFUSED: }"
    exit 2
  fi
  if [ -z "$GUARD_OUT" ]; then log "ERROR: audit dir guard printed nothing"; exit 2; fi
  AUDIT_DIR="$GUARD_OUT"
  mkdir -p "$AUDIT_DIR/cache"
  for cache in grok-cache.json hermes-cache.json cursor-cache.json; do
    if [ -f "$REPO_DIR/data/$cache" ]; then cp "$REPO_DIR/data/$cache" "$AUDIT_DIR/cache/$cache"; fi
  done
  export TOKENSTATS_CACHE_DIR="$AUDIT_DIR/cache"
  LOG_DIR="$AUDIT_DIR"
else
  unset TOKENSTATS_CACHE_DIR  # a live run updates the committed caches in data/
  LOG_DIR="$HOME/Library/Logs"
fi
CACHE_DIR="${TOKENSTATS_CACHE_DIR:-$REPO_DIR/data}"

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
if [ -z "$AUDIT_DIR" ] && [ -d "$LEGACY_LOCK" ]; then
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
# Do not scan into an unresolved merge or somebody else's locked index.
# Audit runs write outside the checkout and can still run during Git work.
if [ -z "$AUDIT_DIR" ]; then
  bash "$REPO_DIR/scripts/publish_tokens.sh" "$REPO_DIR" --lock-held --check-git-idle
fi

# Server drift check FIRST, before any scanning. It compares the committed
# ledger against the public total and re-anchors on >2% drift (observed:
# restart-burst minting took the server from 68.2B to 270.7B in three days).
# It must not wait behind the scans: a hung or aborted scan cycle would take
# the drift protection down with it, which is exactly when it is needed.
if [ -n "$AUDIT_DIR" ]; then
  log "audit mode ($AUDIT_DIR): skipping server drift check"
else
  RECONCILE_LOG="$HOME/Library/Logs/tokenstats-reconcile.log"
  python3 "$REPO_DIR/scripts/reconcile_server.py" >> "$RECONCILE_LOG" 2>&1 \
    && log "server drift check ok" \
    || log "WARNING: server drift check refused or failed (see $RECONCILE_LOG)"
fi

# Under $TMPDIR explicitly: macOS mktemp without a template ignores TMPDIR.
TMP=$(mktemp -d "${TMPDIR%/}/tokenstats.XXXXXX")
LOCAL="$TMP/local"
CLOUD="$TMP/cloud"
MERGED="$TMP/merged"
mkdir -p "$LOCAL" "$CLOUD" "$MERGED"
trap 'rm -rf "$TMP"' EXIT

# --- collect local ccusage sources SEQUENTIALLY. Parallel bunx/ccusage invocations
#     race on the package cache and produced empty/partial JSON (the root cause
#     of the 2026-06-21/22 collection failures). The python true counters can
#     still run in parallel because they don't touch bunx.
SCAN_LOG="$LOG_DIR/tokenstats-scan.log"
: > "$SCAN_LOG"
# Every scan is named in the log with its duration. A failed or timed-out scan
# still falls back to empty JSON (the guards below catch the drop), but it is
# recorded in $SCAN_FAILURES instead of vanishing silently, and a strict run
# refuses to build from it.
SCAN_FAILURES="$TMP/scan-failures.txt"
SCAN_TIMES="$TMP/scan-times.txt"
: > "$SCAN_FAILURES"
: > "$SCAN_TIMES"
# run_scan <name> <out-file> <fallback-json> <command...>
run_scan() {
  local name="$1" out="$2" fallback="$3" started=$SECONDS rc=0 took
  shift 3
  $SCAN_TIMEOUT "$@" > "$out" 2>>"$SCAN_LOG" || rc=$?
  took=$((SECONDS - started))
  if [ "$rc" -eq 0 ]; then
    echo "$name ok ${took}s" >> "$SCAN_TIMES"
    return 0
  fi
  echo "$fallback" > "$out"
  if [ "$rc" -eq 124 ]; then
    log "WARNING: $name timed out after ${took}s (limit ${SCAN_TIMEOUT_SEC}s); empty fallback"
  else
    log "WARNING: $name failed (exit $rc) after ${took}s; empty fallback"
  fi
  echo "$name exit=$rc ${took}s" >> "$SCAN_FAILURES"
}

log "collecting local ccusage…"
if [ "${GROK_HOME+x}" = x ]; then
  case "$GROK_HOME" in
    *,*) log "ERROR: durable Grok collection requires a single GROK_HOME; keeping previous tokens.json"; exit 3 ;;
  esac
  if [ -z "$GROK_HOME" ] || [ ! -d "$GROK_HOME" ]; then
    log "ERROR: explicit GROK_HOME must be an existing directory; keeping previous tokens.json"
    exit 3
  fi
fi
# The durable Grok ledger below already includes the surviving raw logs. Keep
# native Grok out of this one monthly scan so those events enter exactly once.
# The override belongs only to this command: daily activity and the durable
# parser still use the real Grok home, and cloud scans retain their own scope.
if [ "$COUNTER_IS_TURBOTOKENS" = "1" ]; then
  mkdir -p "$TMP/grok-excluded"
  run_scan monthly "$LOCAL/monthly.json" '{"monthly":[]}' \
    env GROK_HOME="$TMP/grok-excluded" $CCUSAGE monthly --json --offline --timezone UTC --by-agent
  python3 "$REPO_DIR/scripts/validate_monthly_scope.py" "$LOCAL/monthly.json"
else
  run_scan monthly "$LOCAL/monthly.json" '{"monthly":[]}' \
    $CCUSAGE monthly --json --offline --timezone UTC
fi
run_scan daily "$LOCAL/daily.json" '{"daily":[]}' \
  $CCUSAGE daily --json --offline --timezone UTC --since "$(date -u -v-35d +%Y-%m-%d)"
# Muse (~/.local/share/muse) needs turbotokens 1.1.6+. An older counter has no
# `muse` command (its `muse --help` still exits 0 with the root help), so ask
# the root help; scanning without support would log a failure and a strict run
# would refuse to build.
COUNTED_AGENTS="claude codex droid kimi opencode"
if [ "$COUNTER_IS_TURBOTOKENS" = "1" ] && $CCUSAGE --help 2>/dev/null | grep -qE '^[[:space:]]+muse[[:space:]]'; then
  COUNTED_AGENTS="$COUNTED_AGENTS muse"
fi
for agent in $COUNTED_AGENTS; do
  run_scan "agent-$agent" "$LOCAL/agent-$agent.json" '{"monthly":[],"totals":{}}' \
    $CCUSAGE "$agent" monthly --json --offline --breakdown
done

log "collecting local true counters…"
# codex/kimi "true" counters exist to undo ccusage bugs: it re-counts Codex's
# repeated token_count events, and reads kimi from user-history. turbotokens
# has neither bug — measured on this dataset, its Codex figure lands within
# 21,530 tokens (0.0001%) of codex_true_usage.py, and its kimi figure is the
# larger, more complete one. So under turbotokens the corrections are noise at
# best and lossy at worst, and codex_true_usage.py is the script that hung the
# collector for 18h on 2026-08-30. Source both from the counter itself; the
# legacy parsers stay for the ccusage fallback path.
EMPTY_TRUE='{"totals":{},"monthly":[]}'
if [ "$COUNTER_IS_TURBOTOKENS" = "1" ]; then
  run_scan codex-true "$LOCAL/codex-true.json" "$EMPTY_TRUE" \
    $CCUSAGE codex monthly --json --offline --breakdown &
  run_scan kimi-true "$LOCAL/kimi-true.json" "$EMPTY_TRUE" \
    $CCUSAGE kimi monthly --json --offline --breakdown &
else
  run_scan codex-true "$LOCAL/codex-true.json" "$EMPTY_TRUE" \
    python3 "$REPO_DIR/scripts/codex_true_usage.py" &
  run_scan kimi-true "$LOCAL/kimi-true.json" "$EMPTY_TRUE" \
    python3 "$REPO_DIR/scripts/kimi_true_usage.py" &
fi
run_scan grok-true "$LOCAL/grok-true.json" "$EMPTY_TRUE" \
  python3 "$REPO_DIR/scripts/grok_true_usage.py" --prior-ledger "$REPO_DIR/data/tokens.json" &
# Cursor dashboard (network); fall back to the committed cache on any failure.
# This is the step that kept hitting the 300s deadline: the true-counter phase
# sat at exactly 5:00 (codex/kimi/grok finish in under a minute) and
# data/cursor-cache.json has not changed since 2026-09-24. cursor_usage.py now
# fetches newest-first under its own 150s budget (CURSOR_BUDGET_SEC).
( started=$SECONDS rc=0
  if [ "$OFFLINE" = "1" ]; then
    rc=offline
  else
    $SCAN_TIMEOUT python3 "$REPO_DIR/scripts/cursor_usage.py" > "$LOCAL/cursor.json" 2>>"$SCAN_LOG" || rc=$?
    if [ "$rc" = "0" ] && [ ! -s "$LOCAL/cursor.json" ]; then rc=empty; fi
  fi
  took=$((SECONDS - started))
  if [ "$rc" = "0" ]; then
    python3 "$REPO_DIR/scripts/atomic_cache.py" "$LOCAL/cursor.json" "$CACHE_DIR/cursor-cache.json" 2>>"$SCAN_LOG" || rc=invalid-cache
  fi
  if [ "$rc" = "0" ]; then
    echo "cursor ok ${took}s" >> "$SCAN_TIMES"
  elif [ -f "$CACHE_DIR/cursor-cache.json" ]; then
    if python3 "$REPO_DIR/scripts/atomic_cache.py" --validate "$CACHE_DIR/cursor-cache.json" 2>>"$SCAN_LOG"; then
      cp "$CACHE_DIR/cursor-cache.json" "$LOCAL/cursor.json"
      echo "cursor cache($rc) ${took}s" >> "$SCAN_TIMES"
      if [ "$rc" != "offline" ]; then
        log "WARNING: cursor dashboard failed ($rc) after ${took}s; using $CACHE_DIR/cursor-cache.json"
      fi
    else
      echo "cursor cache invalid" > "$TMP/cursor-cache-invalid"
      echo "cursor invalid-cache ${took}s" >> "$SCAN_FAILURES"
    fi
  else
    echo "$EMPTY_TRUE" > "$LOCAL/cursor.json"
    echo "cursor exit=$rc ${took}s" >> "$SCAN_FAILURES"
  fi ) &
wait
log "local collected ($(tr '\n' ' ' < "$SCAN_TIMES"))"
if grep -q '^grok-true ' "$SCAN_FAILURES"; then
  log "ERROR: durable Grok scan failed; keeping previous tokens.json (see $SCAN_LOG)"
  exit 3
fi
if [ -f "$TMP/cursor-cache-invalid" ]; then
  log "ERROR: Cursor cache is invalid; keeping previous tokens.json (see $SCAN_LOG)"
  exit 3
fi
if [ -s "$SCAN_FAILURES" ] && [ "$STRICT_SCANS" = "1" ]; then
  log "ERROR: strict scans: $(tr '\n' ' ' < "$SCAN_FAILURES")— not building"
  [ -n "$AUDIT_DIR" ] && cp "$SCAN_FAILURES" "$AUDIT_DIR/scan-failures.txt"
  exit 3
fi

# --- collect from the cloud agent-host. Best-effort: if the box is offline or
#     unreachable, we still publish the local stats.
if [ "$OFFLINE" = "1" ]; then
  log "offline: skipping cloud box; Hermes from its committed cache"
  run_scan hermes-cache "$LOCAL/hermes-true.json" "$EMPTY_TRUE" \
    python3 "$REPO_DIR/scripts/hermes_true_usage.py"
  SOURCES=("$LOCAL")
elif bash "$REPO_DIR/scripts/run_cloud_collection.sh" "$CLOUD" "$LOG_DIR/tokenstats-cloud.log" "$SCAN_TIMEOUT_SEC"; then
  log "cloud collected"
  SOURCES=("$LOCAL" "$CLOUD")
else
  log "WARNING: cloud collection failed (see $LOG_DIR/tokenstats-cloud.log); using local only"
  # Keep hermes history alive from the committed cache so the box being
  # offline can't shrink the totals (hermes-true must exist in exactly ONE
  # source dir — merge sums same-named files across sources).
  python3 "$REPO_DIR/scripts/hermes_true_usage.py" > "$LOCAL/hermes-true.json" 2>>"$SCAN_LOG" \
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
# Frozen baselines are added on top of what the live logs still prove:
#   data/cloud-baseline.json       old agent box, raw logs destroyed in the
#                                  2026-07-05 hermes rebuild (make_cloud_baseline.py)
#   data/local-purge-baseline.json this Mac's Claude Code/Codex transcripts
#                                  deleted by the 2026-10-12 disk cleanup
#                                  (make_purge_baseline.py)
BASELINES=("$REPO_DIR/data/cloud-baseline.json")
PURGE_BASELINE="${TOKENSTATS_PURGE_BASELINE:-$REPO_DIR/data/local-purge-baseline.json}"
if [ "$PURGE_BASELINE" != "none" ]; then
  BASELINES+=("$PURGE_BASELINE")
fi
python3 "$REPO_DIR/scripts/build_tokens_json.py" "$MERGED" "${BASELINES[@]}" > "$TMP/tokens.out"
if [ -n "$AUDIT_DIR" ]; then
  cp "$TMP/tokens.out" "$AUDIT_DIR/tokens.json"
  cp "$SCAN_FAILURES" "$AUDIT_DIR/scan-failures.txt"
  cp "$SCAN_TIMES" "$AUDIT_DIR/scan-times.txt"
fi

# --- safety: all-time totals normally only grow; a drop = a collection glitch.
#     The one exception is the first audited Codex cumulative-delta correction,
#     which intentionally removes duplicated token_count events. ---
OLD=$(python3 -c "import json;print(json.load(open('data/tokens.json'))['totals']['totalTokens'])" 2>/dev/null || echo 0)
NEW=$(python3 -c "import json;print(json.load(open('$TMP/tokens.out'))['totals']['totalTokens'])")
OLD_CODEX_CORRECTED=$(python3 -c "import json;print('1' if json.load(open('data/tokens.json')).get('corrections',{}).get('codexCumulativeAdjusted') else '0')" 2>/dev/null || echo 0)
NEW_CODEX_CORRECTED=$(python3 -c "import json;print('1' if json.load(open('$TMP/tokens.out')).get('corrections',{}).get('codexCumulativeAdjusted') else '0')")
OLD_SOURCES=$(python3 -c "import json;print(','.join(sorted(x['label'] for x in json.load(open('data/tokens.json')).get('sources',[]))))" 2>/dev/null || echo "")
NEW_SOURCES=$(python3 -c "import json;print(','.join(sorted(x['label'] for x in json.load(open('$TMP/tokens.out')).get('sources',[]))))")
if [ "$NEW" -lt "$OLD" ] && ! { [ "$OLD_CODEX_CORRECTED" = 0 ] && [ "$NEW_CODEX_CORRECTED" = 1 ] && [ "$OLD_SOURCES" = "$NEW_SOURCES" ]; }; then
  log "ERROR: new total $NEW < old $OLD — keeping previous tokens.json"; exit 1
fi
# --- safety: each agent's all-time total only grows as well. A timed-out scan
#     falls back to empty and can erase one agent while the overall total
#     still rises (2026-10-20: Codex 39.85B -> 22.69B). Same audited Codex
#     correction exception as above. ---
AGENT_DROPS=$(python3 "$REPO_DIR/scripts/agent_drops.py" data/tokens.json "$TMP/tokens.out")
if [ -n "$AGENT_DROPS" ] && ! { [ "$OLD_CODEX_CORRECTED" = 0 ] && [ "$NEW_CODEX_CORRECTED" = 1 ] && [ "$OLD_SOURCES" = "$NEW_SOURCES" ]; }; then
  log "ERROR: agent total dropped ($AGENT_DROPS) — scan glitch, keeping previous tokens.json"; exit 1
fi
if [ "$NEW" -lt "$OLD" ]; then
  log "audited correction: removing $((OLD - NEW)) duplicated Codex tokens"
fi
if [ -n "$AUDIT_DIR" ]; then
  log "audit mode: guard accepts new total $NEW (old $OLD); wrote $AUDIT_DIR/tokens.json, data/tokens.json untouched"
  exit 0
fi
mv "$TMP/tokens.out" data/tokens.json

if [ "${TOKENSTATS_NO_GIT:-0}" = "1" ]; then
  log "audit mode: rebuilt token artifacts without committing or pushing"
  exit 0
fi


# Retain the collection lock while the publication helper commits and pushes.
bash "$REPO_DIR/scripts/publish_tokens.sh" "$REPO_DIR" --lock-held
