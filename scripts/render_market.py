"""Commit-markets style contribution candle chart.

Renders a 52-week candlestick chart from GitHub contribution data, styled like
https://commit-markets.vercel.app — dark terminal look, dotted grid, green/red
weekly candles with wicks, current-price marker, and a stats header/footer.
"""
import datetime

from common import LOGIN, compact, esc, gh_api, gh_graphql, money, write_svg

MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"

C = {
    "bg": "#0a0c0b",
    "panel": "#0a0c0b",
    "border": "#26292b",
    "grid": "#202624",
    "dot": "#202624",
    "fg": "#e8eae9",
    "muted": "#5c625f",
    "green": "#22c55e",
    "red": "#e5484d",
    "amber": "#f59e0b",
}

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch_calendar():
    now = datetime.datetime.now(datetime.timezone.utc)
    frm = now - datetime.timedelta(days=364)
    cal = gh_graphql(
        QUERY,
        {"login": LOGIN, "from": frm.isoformat(), "to": now.isoformat()},
    )["user"]["contributionsCollection"]["contributionCalendar"]
    return cal


def streaks(counts):
    cur = peak = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        peak = max(peak, run)
    for c in reversed(counts):
        if c > 0:
            cur += 1
        else:
            break
    return cur, peak


def render(gh, tokens):
    cal = fetch_calendar()
    total = cal["totalContributions"]
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    counts = [d["contributionCount"] for d in days]

    # 7-day rolling index = the "price" line; candles sample it per week.
    roll = [sum(counts[max(0, i - 6):i + 1]) for i in range(len(counts))]
    candles, idx = [], 0
    for w in cal["weeks"]:
        k = len(w["contributionDays"])
        seg = roll[idx:idx + k]
        if seg:
            candles.append(
                {
                    "o": seg[0],
                    "c": seg[-1],
                    "h": max(seg),
                    "l": min(seg),
                    "v": sum(counts[idx:idx + k]),
                    "start": w["contributionDays"][0]["date"],
                }
            )
        idx += k
    candles = candles[-52:]

    W, H = 940, 420
    pad = 34
    head_h = 64
    foot_h = 42
    chart_x = pad
    chart_y = head_h + 16
    chart_w = W - pad * 2
    chart_h = H - chart_y - foot_h - 16

    parts = []

    # ---- header ----------------------------------------------------------
    last_px = roll[-1] if roll else 0
    d30 = sum(counts[-30:])
    d30p = sum(counts[-60:-30]) or 1
    delta = 100 * (d30 - d30p) / d30p
    dcol = C["green"] if delta >= 0 else C["red"]

    parts.append(
        f'<text x="{pad}" y="36" font-size="21" font-weight="700" fill="{C["fg"]}">'
        f'$MAXMONEYCASH</text>'
        f'<text x="{pad}" y="54" font-size="11" fill="{C["muted"]}">'
        f'{LOGIN} · github</text>'
        f'<text x="{W - pad}" y="36" text-anchor="end" font-size="26" font-weight="700" fill="{C["fg"]}">'
        f'{last_px:,.2f}</text>'
        f'<rect x="{W - pad - 86}" y="42" width="86" height="20" rx="10" fill="{dcol}" fill-opacity="0.14"/>'
        f'<text x="{W - pad - 43}" y="56" text-anchor="middle" font-size="12" font-weight="600" fill="{dcol}">'
        f'{"▲" if delta >= 0 else "▼"} {abs(delta):.1f}%</text>'
    )

    # ---- chart panel -----------------------------------------------------
    parts.append(
        f'<rect x="{chart_x}" y="{chart_y}" width="{chart_w}" height="{chart_h}" '
        f'rx="12" fill="{C["panel"]}" stroke="{C["border"]}"/>'
        f'<rect x="{chart_x}" y="{chart_y}" width="{chart_w}" height="{chart_h}" '
        f'rx="12" fill="url(#dots)"/>'
    )

    hi = max((c["h"] for c in candles), default=1)
    lo = min((c["l"] for c in candles), default=0)
    span = max(hi - lo, 1)
    hi += span * 0.06
    lo = max(lo - span * 0.05, 0)
    span = hi - lo

    def ys(v):
        return chart_y + 8 + (chart_h - 16) * (1 - (v - lo) / span)

    # horizontal grid + labels
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        v = lo + span * frac
        gy = ys(v)
        parts.append(
            f'<line x1="{chart_x + 10}" y1="{gy:.1f}" x2="{chart_x + chart_w - 10}" y2="{gy:.1f}" '
            f'stroke="{C["grid"]}" stroke-dasharray="3 3"/>'
            f'<text x="{chart_x + chart_w - 6}" y="{gy + 3:.1f}" text-anchor="end" font-size="9" '
            f'fill="{C["muted"]}">{v:,.0f}</text>'
        )

    step = (chart_w - 20) / max(len(candles), 1)
    body_w = max(step * 0.55, 3)

    # subtle close line
    pts = " ".join(
        f"{chart_x + 10 + i * step + body_w / 2:.1f},{ys(c['c']):.1f}"
        for i, c in enumerate(candles)
    )
    parts.append(
        f'<polyline points="{pts}" fill="none" stroke="{C["fg"]}" '
        f'stroke-width="1" opacity="0.12"/>'
    )

    vmax = max((c["v"] for c in candles), default=1) or 1
    for i, c in enumerate(candles):
        x = chart_x + 10 + i * step
        mid = x + body_w / 2
        up = c["c"] >= c["o"]
        color = C["green"] if up else C["red"]
        top, bot = max(c["o"], c["c"]), min(c["o"], c["c"])
        body_h = max(ys(bot) - ys(top), 2)
        parts.append(
            f'<line x1="{mid:.1f}" y1="{ys(c["h"]):.1f}" x2="{mid:.1f}" y2="{ys(c["l"]):.1f}" '
            f'stroke="{color}" stroke-width="1"/>'
            f'<rect x="{x:.1f}" y="{ys(top):.1f}" width="{body_w:.1f}" '
            f'height="{body_h:.1f}" rx="1.5" fill="{color}"/>'
        )

    # current-price marker
    if candles:
        last_y = ys(candles[-1]["c"])
        parts.append(
            f'<line x1="{chart_x + 10}" y1="{last_y:.1f}" x2="{chart_x + chart_w - 10}" y2="{last_y:.1f}" '
            f'stroke="{C["green"]}" stroke-width="1" stroke-dasharray="3 3" opacity="0.7"/>'
            f'<rect x="{chart_x + chart_w - 54}" y="{last_y - 9:.1f}" width="48" height="18" rx="3" fill="{C["green"]}"/>'
            f'<text x="{chart_x + chart_w - 30}" y="{last_y + 4:.1f}" text-anchor="middle" '
            f'font-size="10" font-weight="700" fill="{C["bg"]}">{candles[-1]["c"]}</text>'
        )

    # month labels
    seen = set()
    for wi, c in enumerate(candles):
        mon = datetime.date.fromisoformat(c["start"]).strftime("%b")
        if mon not in seen and wi % 4 == 0:
            seen.add(mon)
            parts.append(
                f'<text x="{chart_x + 10 + wi * step:.1f}" y="{chart_y + chart_h - 8}" '
                f'font-size="9" fill="{C["muted"]}">{mon.upper()}</text>'
            )

    # ---- footer stats ----------------------------------------------------
    cur, peak = streaks(counts)
    active = sum(1 for c in counts if c > 0)
    ath = max((c["v"] for c in candles), default=0)
    fy = H - 22
    parts.append(
        f'<text x="{pad}" y="{fy}" font-size="10" fill="{C["muted"]}">'
        f'52W · COMMIT VELOCITY</text>'
        f'<text x="{W - pad}" y="{fy}" text-anchor="end" font-size="10" fill="{C["muted"]}">'
        f'commit-markets</text>'
        f'<text x="{W / 2}" y="{fy}" text-anchor="middle" font-size="10" fill="{C["fg"]}">'
        f'ATH WEEK <tspan fill="{C["green"]}" font-weight="700">{ath}</tspan>   '
        f'ACTIVE DAYS <tspan fill="{C["green"]}" font-weight="700">{active}/365</tspan>   '
        f'STREAK <tspan fill="{C["green"]}" font-weight="700">{cur}D</tspan>   '
        f'PEAK STREAK <tspan fill="{C["green"]}" font-weight="700">{peak}D</tspan>   '
        f'365D VOL <tspan fill="{C["green"]}" font-weight="700">{total:,}</tspan></text>'
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <pattern id="dots" width="14" height="14" patternUnits="userSpaceOnUse">
    <circle cx="2" cy="2" r="1" fill="{C["dot"]}"/>
  </pattern>
</defs>
<rect width="{W}" height="{H}" rx="14" fill="{C["bg"]}" stroke="{C["border"]}"/>
{''.join(parts)}
</svg>"""
    write_svg("market.svg", svg)
