#!/usr/bin/env bash
# Live status for the 'piles' window: the idea queue, what each agent is on, and
# recent/open PRs across the fleet repos.
export PATH="$HOME/.local/bin:$PATH"
FL="$HOME/fleet"; WORK="$HOME/work"
echo "== PILE (idea queue) =="
shopt -s nullglob
for f in "$FL"/queue/*.task; do sed -n 2p "$f"; done | head -12
[ -z "$(echo "$FL"/queue/*.task)" ] && echo "  (empty — agents self-direct; drop ideas here or label GitHub issues 'agent')"
echo
echo "== AGENTS =="
if [ -f "$FL/assign/panes.txt" ]; then
  while read -r a pane repo; do
    printf "  %-4s [%s] %s\n" "$a" "$repo" "$(head -c 60 "$FL/assign/$a.txt" 2>/dev/null)"
  done < "$FL/assign/panes.txt"
fi
echo
echo "== OPEN PRs =="
while read -r r; do
  [ -d "$WORK/$r/.git" ] || continue
  ( cd "$WORK/$r" && gh pr list --limit 6 --json number,title --jq '.[] | "#\(.number) \(.title)"' 2>/dev/null | sed "s/^/  [$r] /" )
done < "$FL/repos.txt" 2>/dev/null
