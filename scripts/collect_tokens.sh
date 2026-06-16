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

# True codex counts (ccusage <=20.0.11 double-counts re-emitted events)
python3 "$REPO_DIR/scripts/codex_true_usage.py" > "$TMP/codex-true.json"
# Cursor dashboard usage; fall back to the committed cache on any failure
if python3 "$REPO_DIR/scripts/cursor_usage.py" > "$TMP/cursor.json.new" 2>&1; then
  mv "$TMP/cursor.json.new" "$TMP/cursor.json"
  cp "$TMP/cursor.json" data/cursor-cache.json
elif [ -f data/cursor-cache.json ]; then
  echo "cursor fetch failed; using cached data/cursor-cache.json" >&2
  cp data/cursor-cache.json "$TMP/cursor.json"
else
  echo '{"totals":{},"monthly":[]}' > "$TMP/cursor.json"
fi
# Atomic write so a failed build can never truncate data/tokens.json
python3 "$REPO_DIR/scripts/build_tokens_json.py" "$TMP" > "$TMP/tokens.out"
mv "$TMP/tokens.out" data/tokens.json

git add data/tokens.json data/cursor-cache.json
if git diff --cached --quiet; then
  echo "tokens.json unchanged; nothing to push"
  exit 0
fi
git commit -m "chore: daily token stats $(date -u +%Y-%m-%d)"

# The readme/3d workflows also commit to main. Rebase our generated-data commit
# onto theirs, preferring OUR data on conflict (it's the freshest), and ALWAYS
# abort a failed rebase so a half-finished rebase can never wedge every future
# run — that left-behind .git/rebase-merge froze pushes for days in June 2026.
clear_rebase() {
  git rebase --abort 2>/dev/null || true
  rm -rf .git/rebase-merge .git/rebase-apply 2>/dev/null || true
}
clear_rebase  # heal any pre-existing stuck rebase before we start
for i in 1 2 3 4 5; do
  if git fetch -q origin main \
     && git rebase -X theirs origin/main \
     && git push origin main; then
    echo "pushed token stats $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 0
  fi
  clear_rebase
  sleep 5
done
echo "failed to push after 5 attempts" >&2
exit 1
