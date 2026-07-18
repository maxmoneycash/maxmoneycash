#!/bin/bash
# Collect token usage from the cloud agent-host and copy it locally.
#
# The fleet runs headless Claude/Codex on a DigitalOcean box reachable as the
# SSH alias "agent-host". ccusage and the true-counter scripts run there,
# then the JSON outputs are pulled back so the local pipeline can merge them
# with the Mac's own usage.
#
# Usage (from repo root):
#   bash scripts/collect_cloud_tokens.sh <output_dir>
set -euo pipefail

OUT_DIR="${1:-}"
if [ -z "$OUT_DIR" ]; then
  echo "usage: $0 <output_dir>" >&2
  exit 1
fi
mkdir -p "$OUT_DIR"

# Use the SSH alias the user already has in ~/.ssh/config.
HOST="agent-host"
REMOTE_DIR="/tmp/tokenstats-cloud-$$"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

log() { echo "[cloud] $*"; }

log "checking SSH to $HOST"
ssh -o ConnectTimeout=10 "$HOST" "mkdir -p $REMOTE_DIR && node -v && npx --yes ccusage@20.0.9 --version" >/dev/null 2>&1 || {
  echo "ERROR: cannot reach $HOST or ccusage won't run there" >&2
  exit 1
}

# Copy the true-counter scripts we want to run on the box.
scp -q "$REPO_DIR/scripts/codex_true_usage.py" "$REPO_DIR/scripts/kimi_true_usage.py" "$HOST:$REMOTE_DIR/" 2>/dev/null || {
  echo "ERROR: failed to copy scripts to $HOST" >&2
  exit 1
}

log "collecting ccusage from $HOST"
ssh -o ConnectTimeout=30 "$HOST" bash -s -- "$REMOTE_DIR" <<'REMOTE'
set -euo pipefail
REMOTE_DIR="$1"
CCUSAGE="npx --yes ccusage@20.0.9"
cd "$REMOTE_DIR"

$CCUSAGE monthly --json --offline --timezone UTC > monthly.json 2>/dev/null || echo '{"monthly":[],"totals":{}}' > monthly.json
$CCUSAGE daily --json --offline --timezone UTC --since "$(date -u -d '35 days ago' +%Y-%m-%d)" > daily.json 2>/dev/null || echo '{"daily":[],"totals":{}}' > daily.json
for agent in claude codex droid kimi opencode; do
  $CCUSAGE "$agent" monthly --json --offline --breakdown > "agent-$agent.json" 2>/dev/null || echo '{"monthly":[],"totals":{}}' > "agent-$agent.json"
done

python3 "$REMOTE_DIR/codex_true_usage.py" > codex-true.json 2>/dev/null || echo '{"totals":{},"monthly":[]}' > codex-true.json
python3 "$REMOTE_DIR/kimi_true_usage.py" > kimi-true.json 2>/dev/null || echo '{"totals":{},"monthly":[]}' > kimi-true.json

# Hermes gateway (the swarm's token accounting) lives ONLY in its sqlite
# state DBs — ccusage can't see it. Dump per-session counters for the local
# hermes_true_usage.py cache. || fallback keeps the box's other sources alive.
python3 - > hermes-sessions.json 2>/dev/null <<'PYEOF' || echo '[]' > hermes-sessions.json
import glob, json, sqlite3
rows = []
paths = {"main": "/root/.hermes/state.db"}
for p in glob.glob("/root/.hermes/profiles/*/state.db"):
    paths[p.split("/")[-2]] = p
for profile, path in paths.items():
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        for r in con.execute(
            "select id, started_at, model, input_tokens, output_tokens,"
            " cache_read_tokens, cache_write_tokens, reasoning_tokens from sessions"
        ):
            rows.append({"profile": profile, **dict(r)})
        con.close()
    except Exception:
        pass
print(json.dumps(rows))
PYEOF
REMOTE

log "pulling results from $HOST"
scp -q "$HOST:$REMOTE_DIR/*.json" "$OUT_DIR/"

# Fold the hermes session dump into the committed cache and emit the merged
# monthly series. The Hermes `main` profile is mirrored into ccusage's default
# cloud source. Exclude only the current dump's main sessions after proving
# ccusage covers their durable cached values; pruned cache-only sessions remain
# counted forever. The proof and exclusion happen in one process (no TOCTOU).
python3 "$REPO_DIR/scripts/hermes_true_usage.py" \
  "$OUT_DIR/hermes-sessions.json" \
  --exclude-covered-dump-profile main "$OUT_DIR/monthly.json" \
  > "$OUT_DIR/hermes-true.json"
if python3 - "$OUT_DIR/hermes-true.json" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
raise SystemExit(0 if "main" in data.get("excludedProfiles", []) else 1)
PYEOF
then
  log "ccusage covers current Hermes main sessions; fencing duplicates"
else
  log "ccusage does not cover current Hermes main sessions; retaining them"
fi
rm -f "$OUT_DIR/hermes-sessions.json"

# Clean up the remote temp dir.
ssh -o ConnectTimeout=10 "$HOST" "rm -rf $REMOTE_DIR" >/dev/null 2>&1 || true

log "cloud collection complete -> $OUT_DIR"
