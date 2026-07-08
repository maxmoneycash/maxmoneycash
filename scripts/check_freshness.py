"""Guard data/tokens.json freshness from inside readme.yml.

Opens a GitHub issue when the daily push goes stale, and auto-closes it once the
data recovers. Idempotent: never opens a duplicate, and only comments/closes when
there is actually an open issue to act on.
"""
import datetime
import json
import os
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = "maxmoneycash/maxmoneycash"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
# The collector pushes at least hourly and readme.yml runs this check hourly,
# so >8h stale means the pipeline is actually stuck (guard freeze, wedged
# gpg-agent, dead launchd) — alert same-day, not days later.
MAX_AGE_HOURS = 8
TITLE = "Token data stale — launchd push has stopped"


def api(path, data=None, method=None):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(data).encode() if data else None,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "User-Agent": REPO,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def find_open_issue():
    issues = api(f"/repos/{REPO}/issues?state=open&creator=github-actions[bot]")
    return next((i for i in issues if i["title"] == TITLE), None)


def main():
    meta = json.load(open(ROOT / "data" / "tokens.json"))
    gen = datetime.datetime.fromisoformat(meta["generated_at"].replace("Z", "+00:00"))
    age_h = (datetime.datetime.now(datetime.timezone.utc) - gen).total_seconds() / 3600
    print(f"tokens.json age: {age_h:.1f}h (threshold {MAX_AGE_HOURS}h)")

    existing = find_open_issue()

    if age_h <= MAX_AGE_HOURS:
        if existing:
            num = existing["number"]
            api(
                f"/repos/{REPO}/issues/{num}/comments",
                {"body": f"Resolved automatically — data is fresh again ({age_h:.0f}h old). Closing."},
            )
            api(f"/repos/{REPO}/issues/{num}", {"state": "closed"}, method="PATCH")
            print(f"closed staleness issue #{num} (data recovered)")
        return

    if existing:
        print(f"staleness issue #{existing['number']} already open")
        return

    api(
        f"/repos/{REPO}/issues",
        {
            "title": TITLE,
            "body": (
                f"`data/tokens.json` is **{age_h:.0f}h old** (threshold {MAX_AGE_HOURS}h).\n\n"
                "The daily token push from the Mac has likely stopped. Check:\n"
                "```\ntail -20 ~/Library/Logs/tokenstats.log\n"
                "launchctl list | grep tokenstats\n```\n"
                "Re-arm with `launchctl kickstart -k gui/$(id -u)/com.maxmoneycash.tokenstats`, "
                "or re-run the installers: `bash scripts/install_launchd.sh && bash scripts/install_claude_hook.sh`.\n\n"
                "_This issue auto-closes once fresh data is pushed._"
            ),
        },
    )
    print("opened staleness issue")


if __name__ == "__main__":
    main()
