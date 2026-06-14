# tokenstats launchd agent

Drives the daily local token collection (`scripts/collect_tokens.sh`) on the
Mac, which is the upstream source for the README cards. GitHub Actions only
*renders* what this pushes — if this agent stops, the README freezes on the
last pushed `data/tokens.json`.

## Install / update

```bash
bash scripts/install_launchd.sh
```

Renders `com.maxmoneycash.tokenstats.plist` (a template with `__REPO_DIR__` /
`__HOME__` placeholders) into `~/Library/LaunchAgents/`, loads it, and kicks it
once. Re-run after pulling changes to the plist.

## Why both StartInterval and StartCalendarInterval

`StartCalendarInterval` alone is brittle: if the Mac is asleep at the scheduled
time, the run is skipped and the README goes stale until the next day. The added
`StartInterval` (6h) catch-up fires once on wake after a missed interval, and
`RunAtLoad` covers reboots — so sleeping through a window no longer drops the
push.

## Manual controls

```bash
launchctl kickstart -k gui/$(id -u)/com.maxmoneycash.tokenstats   # run now
launchctl list | grep tokenstats                                  # status
tail -20 ~/Library/Logs/tokenstats.log                            # logs
launchctl bootout gui/$(id -u)/com.maxmoneycash.tokenstats        # uninstall
```
