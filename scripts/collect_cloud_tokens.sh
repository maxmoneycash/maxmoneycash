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
REMOTE

log "pulling results from $HOST"
scp -q "$HOST:$REMOTE_DIR/*.json" "$OUT_DIR/"

# Clean up the remote temp dir.
ssh -o ConnectTimeout=10 "$HOST" "rm -rf $REMOTE_DIR" >/dev/null 2>&1 || true

log "cloud collection complete -> $OUT_DIR"
