"""Pull historical Cursor usage (per-month, per-model tokens) for an
individual account via the cursor.com dashboard endpoints.

The official Admin/Analytics APIs are Enterprise-team-only, so this uses
the same calls the dashboard's Usage tab makes, authenticated with a
WorkosCursorSessionToken cookie built from the local Cursor install's
cursorAuth/accessToken (the cursor-stats extension's method). If auth is
stale, emits zeroed output with an "error" note so the pipeline degrades
gracefully.
"""
import base64
import datetime
import json
import pathlib
import sqlite3
import sys
import urllib.request

DB = (
    pathlib.Path.home()
    / "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
)
EMPTY = {
    "totals": {
        "inputTokens": 0, "outputTokens": 0, "cacheCreationTokens": 0,
        "cacheReadTokens": 0, "totalTokens": 0, "totalCost": 0.0,
    },
    "monthly": [],
}
START = (2023, 1)


def bail(reason):
    # Fail loudly; collect_tokens.sh falls back to the committed cache.
    print(f"cursor_usage: {reason}", file=sys.stderr)
    sys.exit(1)


def cookie():
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
        row = con.execute(
            "SELECT value FROM ItemTable WHERE key='cursorAuth/accessToken'"
        ).fetchone()
        con.close()
    except Exception as e:
        bail(f"db: {e}")
    if not row:
        bail("no accessToken in state.vscdb")
    jwt = row[0].strip('"')
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        sub = json.loads(base64.urlsafe_b64decode(payload))["sub"]
        user_id = sub.split("|")[-1]
    except Exception as e:
        bail(f"jwt: {e}")
    return f"WorkosCursorSessionToken={user_id}%3A%3A{jwt}"


def post(path, body, ck):
    req = urllib.request.Request(
        f"https://cursor.com{path}",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Cookie": ck,
            "Origin": "https://cursor.com",
            "Referer": "https://cursor.com/dashboard",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def month_iter():
    y, m = START
    now = datetime.datetime.now(datetime.timezone.utc)
    while (y, m) <= (now.year, now.month):
        start = datetime.datetime(y, m, 1, tzinfo=datetime.timezone.utc)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        end = datetime.datetime(ny, nm, 1, tzinfo=datetime.timezone.utc)
        yield f"{y:04d}-{m:02d}", int(start.timestamp() * 1000), int(
            min(end, now).timestamp() * 1000
        )
        y, m = ny, nm


def main():
    ck = cookie()
    monthly = []
    totals = {k: 0 for k in EMPTY["totals"]}
    totals["totalCost"] = 0.0
    try:
        for month, s_ms, e_ms in month_iter():
            data = None
            for attempt in range(3):
                try:
                    data = post(
                        "/api/dashboard/get-aggregated-usage-events",
                        {"teamId": -1, "startDate": str(s_ms), "endDate": str(e_ms)},
                        ck,
                    )
                    break
                except TimeoutError:
                    continue
            if data is None:
                bail(f"month {month} failed after retries")
            aggs = data.get("aggregations") or []
            if not aggs:
                continue
            entry = {
                "month": month, "inputTokens": 0, "outputTokens": 0,
                "cacheCreationTokens": 0, "cacheReadTokens": 0,
                "totalTokens": 0, "totalCost": 0.0, "models": {},
            }
            for a in aggs:
                mi = int(a.get("inputTokens") or 0)
                mo = int(a.get("outputTokens") or 0)
                mw = int(a.get("cacheWriteTokens") or 0)
                mr = int(a.get("cacheReadTokens") or 0)
                cents = float(a.get("totalCents") or 0)
                model = a.get("modelIntent") or a.get("model") or "cursor-unknown"
                entry["inputTokens"] += mi
                entry["outputTokens"] += mo
                entry["cacheCreationTokens"] += mw
                entry["cacheReadTokens"] += mr
                entry["totalCost"] += cents / 100
                tot = mi + mo + mw + mr
                if tot:
                    mm = entry["models"].setdefault(model, {
                        "inputTokens": 0, "outputTokens": 0,
                        "cacheCreationTokens": 0, "cacheReadTokens": 0,
                        "totalTokens": 0, "cost": 0.0,
                    })
                    mm["inputTokens"] += mi
                    mm["outputTokens"] += mo
                    mm["cacheCreationTokens"] += mw
                    mm["cacheReadTokens"] += mr
                    mm["totalTokens"] += tot
                    mm["cost"] += cents / 100
            entry["totalTokens"] = (
                entry["inputTokens"] + entry["outputTokens"]
                + entry["cacheCreationTokens"] + entry["cacheReadTokens"]
            )
            if entry["totalTokens"] or entry["totalCost"]:
                monthly.append(entry)
                for k in ("inputTokens", "outputTokens", "cacheCreationTokens",
                          "cacheReadTokens", "totalTokens"):
                    totals[k] += entry[k]
                totals["totalCost"] += entry["totalCost"]
    except urllib.error.HTTPError as e:
        bail(f"http {e.code}")
    json.dump({"totals": totals, "monthly": monthly}, sys.stdout)


if __name__ == "__main__":
    main()
