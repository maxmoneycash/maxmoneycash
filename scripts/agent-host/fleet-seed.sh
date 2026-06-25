#!/usr/bin/env bash
# Seed each interactive agent once claude has booted: give it the self-looping
# hackathon mission. Runs as a detached tmux window so it survives ExecStartPre.
#   bash fleet-seed.sh [boot_wait_seconds]
set -uo pipefail
FL="$HOME/fleet"
sleep "${1:-15}"   # let the claude TUIs finish booting before typing
[ -f "$FL/assign/panes.txt" ] || exit 0
mission_extra=""
[ -f "$FL/mission.txt" ] && mission_extra=" Mission context: $(tr '\n' ' ' < "$FL/mission.txt")"
mapfile -t LINES < "$FL/assign/panes.txt"
total=${#LINES[@]}; idx=0
repos_all=$(tr '\n' ' ' < "$FL/repos.txt" 2>/dev/null)
for line in "${LINES[@]}"; do
  read -r a pane repo <<< "$line"
  [ -n "${pane:-}" ] || continue
  idx=$((idx+1))
  if [ "${DEMO_DIRECTOR:-0}" = "1" ] && [ "$total" -gt 1 ] && [ "$idx" -eq "$total" ]; then
    # last agent = DEMO DIRECTOR (testing + presentation) — enable with DEMO_DIRECTOR=1
    seed="You are $a, the DEMO DIRECTOR with FULL PERMISSIONS and full access, for a Sui hackathon DUE TOMORROW across these repos: $repos_all.${mission_extra} Your job: make the projects DEMOABLE and figure out how to PRESENT everything to win. LOOP: (1) write a 3-6 word task name to ~/fleet/assign/$a.txt, (2) end-to-end DOGFOOD each repo's full demo path — build it, run the dev server, exercise the real user flow, and use playwright headless chromium to click through and SCREENSHOT key screens, (3) fix small bugs you find and note big ones clearly, (4) build the PRESENTATION: a DEMO.md per repo (what it is, why it wins, the exact 60-second demo script, the Sui on-chain proof, architecture) plus a short pitch and the screenshots (and a live deploy URL if one is set up), (5) MERGE your work to main, then repeat. No force-push or history rewrite. The human may redirect you anytime — honor it. Begin now."
  else
    # builders = ship features to main, tested
    seed="You are $a with FULL PERMISSIONS and full repo + system access, working UNATTENDED but INTERACTIVELY on '$repo', a Sui hackathon entry DUE TOMORROW. Build to WIN.${mission_extra} Use the codebase-memory MCP tools (get_architecture, search_graph, trace_path, detect_changes, get_code_snippet) to understand and navigate this repo from its persistent index INSTEAD of re-reading files each time — that is your long-term memory. LOOP: (1) write a 3-6 word task name to ~/fleet/assign/$a.txt, (2) implement the highest-value improvement, (3) DOGFOOD it — build, run, and TEST it for real (write/run unit + e2e tests; use playwright headless chromium for the UI), fixing until it actually works, (4) ONLY when it builds and works, MERGE IT TO MAIN (commit, push, then 'gh pr merge --squash --admin' or push to main), (5) repeat. CRITICAL: always run the production build (same as Vercel — npm/pnpm/bun run build) and ensure it PASSES before pushing; a pre-push hook will BLOCK the push if the build fails (read /tmp/prepush-build.log, fix, retry). Never ship a broken build to prod. No force-push or history rewrite. The human may type here anytime to redirect you — honor it. Begin now."
  fi
  tmux send-keys -t "$pane" Enter; sleep 2   # accept any "trust this folder?" prompt on a fresh worktree
  tmux send-keys -t "$pane" "$seed"
  sleep 1; tmux send-keys -t "$pane" Enter   # submit
  sleep 1; tmux send-keys -t "$pane" Enter   # beat the paste-needs-second-Enter quirk
  sleep 3
done
echo "seeded $(wc -l < "$FL/assign/panes.txt" 2>/dev/null) agents"
