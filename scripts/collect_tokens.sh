#!/bin/bash
# Collects AI-agent token usage via ccusage and writes data/tokens.json.
# Runs locally (the usage logs only exist on this machine), then commits
# and pushes so the GitHub Action can re-render the README cards.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# --bun forces the bun runtime: /usr/local/bin/node is an x86_64 leftover and
# the ccusage wrapper otherwise spawns it and looks for the wrong native binary.
CCUSAGE="${CCUSAGE:-bunx --bun ccusage@20.0.9}"
export PATH="$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

cd "$REPO_DIR"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

$CCUSAGE monthly --json --offline --timezone UTC > "$TMP/monthly.json"
$CCUSAGE daily   --json --offline --timezone UTC --since "$(date -u -v-35d +%Y-%m-%d)" > "$TMP/daily.json"

# Per-agent totals + per-model breakdowns (unified JSON has no per-agent split)
for agent in claude codex droid kimi opencode; do
  $CCUSAGE "$agent" monthly --json --offline --breakdown > "$TMP/agent-$agent.json" 2>/dev/null \
    || echo '{"monthly":[],"totals":{}}' > "$TMP/agent-$agent.json"
done

jq -n \
  --slurpfile monthly "$TMP/monthly.json" \
  --slurpfile daily "$TMP/daily.json" \
  --slurpfile claude "$TMP/agent-claude.json" \
  --slurpfile codex "$TMP/agent-codex.json" \
  --slurpfile droid "$TMP/agent-droid.json" \
  --slurpfile kimi "$TMP/agent-kimi.json" \
  --slurpfile opencode "$TMP/agent-opencode.json" \
  '{
    generated_at: (now | todate),
    totals: $monthly[0].totals,
    monthly: $monthly[0].monthly,
    daily: $daily[0].daily,
    agents: {
      claude:   {totals: $claude[0].totals,   monthly: $claude[0].monthly},
      codex:    {totals: $codex[0].totals,    monthly: $codex[0].monthly},
      droid:    {totals: $droid[0].totals,    monthly: $droid[0].monthly},
      kimi:     {totals: $kimi[0].totals,     monthly: $kimi[0].monthly},
      opencode: {totals: $opencode[0].totals, monthly: $opencode[0].monthly}
    }
  }' > data/tokens.json

git add data/tokens.json
if git diff --cached --quiet; then
  echo "tokens.json unchanged; nothing to push"
  exit 0
fi
git commit -m "chore: daily token stats $(date -u +%Y-%m-%d)"
# The readme/3d workflows also commit to main; rebase-and-retry around them.
for i in 1 2 3 4 5; do
  git pull --rebase origin main && git push origin main && {
    echo "pushed token stats $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 0
  }
  sleep 5
done
echo "failed to push after 5 attempts" >&2
exit 1
