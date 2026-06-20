#!/usr/bin/env bash
# Refresh live app screenshots for the holdings showcase, then commit+push.
# Reads scripts/showcase.json (shared with render_holdings.py) and screenshots
# each live URL with agent-browser (local Chromium). Best-effort: a URL that
# fails keeps its last committed shot. Standalone on purpose — kept out of the
# critical token-push path so it can never delay or block daily stats.
#
#   bash scripts/screenshot_apps.sh
set -uo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$REPO_DIR/assets/shots"
mkdir -p "$DEST"
cd "$REPO_DIR"

if ! command -v agent-browser >/dev/null 2>&1; then
  echo "agent-browser not available; keeping committed shots" >&2
  exit 0
fi

agent-browser set viewport 1280 800 >/dev/null 2>&1 || true
python3 -c "import json;[print(h['repo'], h['url']) for h in json.load(open('scripts/showcase.json'))['holdings'] if h.get('url')]" \
| while read -r name url; do
  agent-browser open "$url" >/dev/null 2>&1 || { echo "skip $name (open failed)"; continue; }
  agent-browser wait --load networkidle >/dev/null 2>&1 || true
  agent-browser wait 3000 >/dev/null 2>&1 || true
  tmp="$DEST/.$name.png"
  if agent-browser screenshot "$tmp" >/dev/null 2>&1 && [ -s "$tmp" ]; then
    sips -s format jpeg -s formatOptions 64 --resampleWidth 760 "$tmp" --out "$DEST/$name.jpg" >/dev/null 2>&1 \
      && { rm -f "$tmp"; echo "refreshed $name"; } \
      || echo "compress failed $name"
  else
    rm -f "$tmp" 2>/dev/null; echo "shot failed $name"
  fi
done

git add assets/shots
if git diff --cached --quiet; then
  echo "no screenshot changes"
  exit 0
fi
git commit -m "chore: refresh live app screenshots $(date -u +%Y-%m-%d)"
for i in 1 2 3 4 5; do
  git fetch -q origin main && git rebase -X ours origin/main >/dev/null 2>&1 && git push -q origin main && {
    echo "pushed screenshots"; exit 0; }
  git rebase --abort 2>/dev/null || true; rm -rf .git/rebase-merge 2>/dev/null || true; sleep 5
done
echo "screenshot push failed" >&2
