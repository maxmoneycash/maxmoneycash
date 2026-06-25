#!/usr/bin/env bash
# Add N more interactive agents to the RUNNING dash (no restart, preserves agents
# already working). Round-robins over repos.txt, makes a worktree per agent, seeds
# each with the full-access build-gated mandate.
#   bash fleet-add.sh <N>
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"; export XDG_RUNTIME_DIR=/run/user/$(id -u)
FL="$HOME/fleet"; WORK="$HOME/work"
N="${1:-2}"
mapfile -t REPOS < "$FL/repos.txt"; [ "${#REPOS[@]}" -gt 0 ] || REPOS=(sui-options)
cur=$(wc -l < "$FL/assign/panes.txt" 2>/dev/null || echo 0)
new=()
for ((k=1; k<=N; k++)); do
  a=$((cur + k)); name="a$a"
  repo="${REPOS[$(((a-1) % ${#REPOS[@]}))]}"
  wt="$FL/wt/a$a"
  ( cd "$WORK/$repo" 2>/dev/null || exit 0
    git fetch -q origin 2>/dev/null
    def=$(git remote show origin 2>/dev/null | sed -n 's/.*HEAD branch: //p'); def="${def:-main}"
    git worktree remove --force "$wt" 2>/dev/null; rm -rf "$wt"
    git worktree add -q -b "agent$a/$(date -u +%H%M%S)" "$wt" "origin/$def" 2>/dev/null )
  echo "starting…" > "$FL/assign/$name.txt"
  tmux split-window -t dash:agents "cd '$wt' && clear && echo '$name -> $repo · type to talk' && while true; do claude --dangerously-skip-permissions; echo '— restarting in 3s —'; sleep 3; done"
  tmux select-layout -t dash:agents tiled >/dev/null
  pane=$(tmux list-panes -t dash:agents -F '#{pane_id}' | tail -1)
  tmux select-pane -t "$pane" -T "$name · $repo · starting…"
  echo "$name $pane $repo" >> "$FL/assign/panes.txt"
  new+=("$name $pane $repo"); echo "added $name -> $repo ($pane)"
done
echo "waiting for claude to boot before seeding…"; sleep 20
for e in "${new[@]}"; do
  read -r name pane repo <<< "$e"
  tmux send-keys -t "$pane" Enter; sleep 2   # accept trust-folder prompt
  seed="You are $name with FULL PERMISSIONS and full repo + system access on '$repo', a Sui hackathon entry DUE TODAY. Build to WIN. Use the codebase-memory MCP (get_architecture, search_graph, trace_path, get_code_snippet) as your memory. LOOP: (1) write a 3-6 word task name to ~/fleet/assign/$name.txt; (2) implement the highest-value improvement; (3) DOGFOOD it (build + run); the pre-push hook runs the production build and BLOCKS broken pushes, so never ship a broken build; (4) when it builds, MERGE TO MAIN; (5) repeat. No force-push or history rewrite. The human may type here anytime to redirect you. Begin now."
  tmux send-keys -t "$pane" -l "$seed"; sleep 1; tmux send-keys -t "$pane" Enter; sleep 1; tmux send-keys -t "$pane" Enter
  echo "seeded $name"
done
