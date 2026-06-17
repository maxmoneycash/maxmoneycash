# 24/7 agent host

Run Claude Code agents day and night on a cheap always-on cloud box, billed to
your **Max subscription** (not the metered API), pacing itself around the
5-hour / weekly limits.

## Why a separate box
Your laptop being closed is what froze the README before. An always-on $4/mo VPS
runs the agents *and* the daily token-stats job, so nothing depends on your Mac.

## The honest constraint
The Max plan caps usage on a rolling 5-hour window and a weekly window
(use-it-or-lose-it — nothing accumulates). So this is **not literally nonstop**:
the runner works in bounded jobs and sleeps when capped, spreading your weekly
allowance across the nights at **zero marginal cost**. True 24/7 continuous would
require metered API ($$$), which this box deliberately avoids by never setting
`ANTHROPIC_API_KEY`.

## Provision (≈10 min)
Any **4 GB+ RAM Ubuntu 22.04/24.04** box works (4 GB is the Claude Code minimum) —
the steps below are identical on every provider. Easiest options:

- **DigitalOcean (recommended):** Create Droplet → Ubuntu 24.04 → Basic / Regular
  / 4 GB ($24/mo). Use the in-browser **Console** so you don't need SSH keys/terminal.
- **AWS:** use **Lightsail** (not raw EC2) → Linux/Ubuntu → 4 GB plan (~$24/mo),
  also has a browser SSH console.
- **GCP:** Compute Engine → `e2-medium` (2 vCPU, 4 GB), Ubuntu 24.04. New accounts
  usually get $300/90-day free credit.
- **Not Cloudflare:** no persistent always-on Linux VM / SSH box — wrong shape.

1. Create the box (above), open its web console or SSH in.
2. Then:
   ```bash
   git clone https://github.com/maxmoneycash/maxmoneycash.git
   bash maxmoneycash/scripts/agent-host/bootstrap.sh
   ```
3. Log Claude Code into your subscription (one-time, works over SSH):
   ```bash
   claude          # pick Subscription, open the URL on your phone, paste the code
   /status         # confirm it shows your Max plan, NOT an API key
   ```
4. Start the paced runner:
   ```bash
   bash ~/work/maxmoneycash/scripts/agent-host/paced-runner.sh --install
   journalctl --user -u agent-runner -f
   ```

## Defaults (all configurable)
- **Subscription-only.** `ANTHROPIC_API_KEY` is refused — capped = sleep, never spend.
- **PR-only.** Branch + PR; never pushes `main`. Set `PUSH=1` after adding a
  GitHub token / `gh auth login` on the box.
- **Paced.** One bounded job at a time; any failure or cap → back off 30 min → retry.
- **Worklist-driven.** Edit `worklist.md`; the runner pulls the top unchecked task.

## Phases
- **Phase 1 (this):** Claude Code itself, sub-auth, paced, PR-only.
- **Phase 2:** move the token-stats launchd job here as a cron/systemd timer
  (kills the laptop dependency for the live README).
- **Phase 3:** add Hermes (orchestrator) + Droid (worker) on the same sub auth,
  once their headless subscription login is verified on the live box.

## Watch / control
```bash
journalctl --user -u agent-runner -f        # live logs
tail -f ~/agent-runner.log                   # job history
systemctl --user stop agent-runner           # pause
npx -y ccusage@latest blocks --active        # see current window usage
```
