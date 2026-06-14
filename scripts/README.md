# How the README stats stay fresh

GitHub Actions only **renders** the cards. The numbers come from `ccusage` reading
local agent logs on the Mac, written to `data/tokens.json`, and pushed. Three
layers keep that push happening so the README never silently freezes:

| Layer | Trigger | Covers |
|---|---|---|
| **Per-session hook** | Claude Code `SessionEnd` | Updates right after each coding session — the work you just did |
| **launchd interval** | every 6h + on wake/boot | Catch-up if the Mac slept through a window, or coding happened outside Claude Code |
| **Freshness guard** | inside `readme.yml` | Opens a GitHub issue if `tokens.json` goes >48h stale |

All three run the same `collect_tokens.sh`, which no-ops when the data is
unchanged, so overlapping triggers are cheap.

## One-time setup on the Mac

```bash
bash scripts/install_launchd.sh     # interval + wake/boot catch-up
bash scripts/install_claude_hook.sh # per-session updates, every repo
```

- `install_launchd.sh` — see `scripts/launchd/README.md`.
- `install_claude_hook.sh` — adds the `SessionEnd` hook to `~/.claude/settings.json`
  so **every** Claude Code session (in any repo) refreshes stats. This repo also
  ships a per-repo hook in `.claude/settings.json`, so sessions opened here work
  even without the global install.

## The hook (`claude_session_hook.sh`)

Fires after a session ends and detaches a background worker that runs the
collector. It is guarded to no-op unless it's the owner's clone on macOS with
`bun` available, so it's safe in cloud sessions, forks, and other machines. A
mkdir lock prevents overlapping sessions from stacking pushes. Logs to
`~/Library/Logs/tokenstats.log` (same log as launchd).
