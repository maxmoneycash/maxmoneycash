# Overnight worklist

One task per `- [ ]` line. The paced runner takes the first unchecked task,
runs it as a bounded Claude Code job on a fresh branch, opens a PR (or commits
to a branch), then checks it off. Keep tasks small, self-contained, and
verifiable. Anything risky or ambiguous: leave it OUT — this box runs unattended.

## Rules the runner injects into every job
- Work only inside the named repo. Never touch unrelated repos or system config.
- Make the smallest change that satisfies the task. No drive-by refactors.
- If the task is unclear or needs a decision, STOP and leave a note in the PR
  body instead of guessing.
- Never push to `main`. Branch + PR only.

## Queue
- [ ] maxmoneycash: add per-repo language-breakdown card to the profile README pipeline
- [ ] commit-markets: add a 30-day sparkline to each ticker card on the discovery board
- [ ] seammoney: verify org README renders correctly at mobile width and fix any overflow
- [ ] maxmoneycash: write unit tests for scripts/codex_true_usage.py against the /tmp fixtures
