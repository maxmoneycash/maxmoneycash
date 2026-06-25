#!/usr/bin/env bash
# Set up the fleet scope: make dirs, clone the named repos, write repos.txt.
#   bash fleet.sh --setup <repo> [repo ...]
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
HERE="$(cd "$(dirname "$0")" && pwd)"
FLEET="$HOME/fleet"; WORK="$HOME/work"
mkdir -p "$FLEET"/{queue,cur,done,failed,log,wt} "$WORK"
shift || true   # drop the --setup arg
: > "$FLEET/repos.txt"
for name in "$@"; do
  if [ ! -d "$WORK/$name/.git" ]; then
    owner=""
    for o in maxmoneycash seammoney; do
      gh repo view "$o/$name" >/dev/null 2>&1 && { owner="$o"; break; }
    done
    if [ -z "$owner" ]; then
      # last resort: search across GitHub for an exact-name repo you can access
      owner=$(gh search repos "$name" --limit 10 --json fullName --jq \
        ".[] | select(.fullName | endswith(\"/$name\")) | .fullName" 2>/dev/null | head -1 | cut -d/ -f1)
    fi
    if [ -n "$owner" ]; then echo "clone $owner/$name"; gh repo clone "$owner/$name" "$WORK/$name" -- -q 2>/dev/null || echo "  clone FAILED $owner/$name"
    else echo "  NOT FOUND on GitHub: $name"; fi
  else echo "have $name"; fi
  if [ -d "$WORK/$name/.git" ]; then
    echo "$name" >> "$FLEET/repos.txt"
    # install the pre-push build gate (shared by all worktrees of this repo)
    if cp "$HERE/fleet-prepush-hook.sh" "$WORK/$name/.git/hooks/pre-push" 2>/dev/null; then
      chmod +x "$WORK/$name/.git/hooks/pre-push"; echo "  pre-push build gate installed for $name"
    fi
  fi
done
echo "=== fleet repos.txt ==="; cat "$FLEET/repos.txt" 2>/dev/null || echo "(none)"
