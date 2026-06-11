"""Open a GitHub issue if data/tokens.json goes stale (launchd push died).

Runs inside readme.yml. Idempotent: skips if an open staleness issue exists.
"""
import datetime
import json
import os
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = "maxmoneycash/maxmoneycash"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
MAX_AGE_HOURS = 48
TITLE = "Token data stale — launchd push has stopped"


def api(path, data=None):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(data).encode() if data else None,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "User-Agent": REPO,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main():
    meta = json.load(open(ROOT / "data" / "tokens.json"))
    gen = datetime.datetime.fromisoformat(meta["generated_at"].replace("Z", "+00:00"))
    age_h = (datetime.datetime.now(datetime.timezone.utc) - gen).total_seconds() / 3600
    print(f"tokens.json age: {age_h:.1f}h")
    if age_h <= MAX_AGE_HOURS:
        return
    open_issues = api(f"/repos/{REPO}/issues?state=open&creator=github-actions[bot]")
    if any(i["title"] == TITLE for i in open_issues):
        print("staleness issue already open")
        return
    api(
        f"/repos/{REPO}/issues",
        {
            "title": TITLE,
            "body": (
                f"`data/tokens.json` is **{age_h:.0f}h old** (threshold {MAX_AGE_HOURS}h).\n\n"
                "The daily launchd job on the Mac has likely stopped pushing. Check:\n"
                "```\ntail -20 ~/Library/Logs/tokenstats.log\n"
                "launchctl list | grep tokenstats\n```\n"
                "Re-arm with `launchctl kickstart gui/$(id -u)/com.maxmoneycash.tokenstats`."
            ),
        },
    )
    print("opened staleness issue")


if __name__ == "__main__":
    main()
