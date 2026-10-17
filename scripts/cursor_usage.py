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
import os
import pathlib
import ssl
import sqlite3
import sys
import time
import urllib.request

try:
    import certifi
except ImportError:
    certifi = None

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
# Cursor's dashboard was request-counted before July 2025, so earlier calls
# cannot contribute token-accounted rows and only slow or destabilize refreshes.
START = (2025, 7)
# TOKENSTATS_CACHE_DIR: a sandboxed audit run keeps its caches out of data/.
CACHE = pathlib.Path(
    os.environ.get("TOKENSTATS_CACHE_DIR")
    or pathlib.Path(__file__).resolve().parent.parent / "data"
) / "cursor-cache.json"
# Wall-clock budget for dashboard requests, well inside the collector's 300s
# per-scan deadline. Fetching all ~16 months oldest-first used to run into that
# deadline on every collection since 2026-09-24: the whole script was killed,
# the cache never updated, and the current month was never counted. Months are
# now fetched newest-first (only recent months can still change) and, once the
# budget is spent, the rest are served from their last known-good cached rows.
BUDGET_SEC = float(os.environ.get("CURSOR_BUDGET_SEC", "150"))


def cached_months():
    """Last known-good month rows, keyed by month.

    Cursor's dashboard returns a hard 500 for some historical months —
    2025-09 has failed every request since at least 2026-08-26 while every
    other month, including the current one, succeeds. Losing an entire
    collection because one immutable past month is broken on their side threw
    away live data and left the whole Cursor agent on a stale cache.
    """
    try:
        rows = json.loads(CACHE.read_text()).get("monthly") or []
    except Exception:
        return {}
    return {r["month"]: r for r in rows if isinstance(r, dict) and r.get("month")}


def tls_context():
    """Use certifi when the framework Python has no usable system CA store."""
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


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
    with urllib.request.urlopen(req, timeout=45, context=tls_context()) as r:
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


def month_entry(month, aggs):
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
    return entry


def collect(months, fetch, cache, clock=time.monotonic, budget=BUDGET_SEC,
            sleep=time.sleep):
    """Fetch months newest-first within the time budget; any month not
    fetched (budget spent, timeouts, 5xx) reuses its cached row. Raises
    urllib.error.HTTPError for 4xx."""
    started = clock()
    rows = {}
    degraded = []
    for month, s_ms, e_ms in sorted(months, reverse=True):
        data = None
        last_error = "time budget"
        for attempt in range(3):
            if clock() - started > budget:
                break
            try:
                data = fetch(s_ms, e_ms)
                break
            except TimeoutError:
                last_error = "timeout"
                continue
            except urllib.error.HTTPError as err:
                last_error = f"http {err.code}"
                # 4xx is a real client/auth problem and will not improve.
                if err.code < 500:
                    raise
                sleep(1 + attempt)
        if data is None:
            # Reuse this month's last known-good row. Past months are
            # immutable, so a cached value is the correct answer, not a
            # guess — and it keeps totals monotonic for the collector's
            # glitch guard.
            degraded.append(f"{month} ({last_error})")
            if cache.get(month):
                rows[month] = cache[month]
            continue
        aggs = data.get("aggregations") or []
        if not aggs:
            continue
        entry = month_entry(month, aggs)
        if entry["totalTokens"] or entry["totalCost"]:
            rows[month] = entry
    monthly = [rows[m] for m in sorted(rows)]
    totals = {k: 0 for k in EMPTY["totals"]}
    totals["totalCost"] = 0.0
    for row in monthly:
        for k in ("inputTokens", "outputTokens", "cacheCreationTokens",
                  "cacheReadTokens", "totalTokens"):
            totals[k] += row.get(k, 0) or 0
        totals["totalCost"] += row.get("totalCost", 0) or 0
    return {"totals": totals, "monthly": monthly}, degraded


def main():
    ck = cookie()
    cache = cached_months()

    def fetch(s_ms, e_ms):
        return post(
            "/api/dashboard/get-aggregated-usage-events",
            {"teamId": -1, "startDate": str(s_ms), "endDate": str(e_ms)},
            ck,
        )

    try:
        out, degraded = collect(list(month_iter()), fetch, cache)
    except urllib.error.HTTPError as e:
        bail(f"http {e.code}")
    if degraded:
        # stderr is captured to tokenstats-scan.log, so a partial collection is
        # visible rather than silently indistinguishable from a clean one.
        served = sum(1 for d in degraded if d.split()[0] in cache)
        print(
            f"cursor_usage: {len(degraded)} month(s) unavailable "
            f"({', '.join(degraded)}); {served} served from cache",
            file=sys.stderr,
        )
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
