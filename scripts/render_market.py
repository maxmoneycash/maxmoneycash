"""Perps-terminal dashboard: contribution activity as a real candle chart.

The price series is a 7-day rolling contribution index sampled daily, so
candles wrap around a continuous line (open ≈ prior close) instead of
hugging zero on weekend-bounded weeks. Volume = raw weekly contributions.
Asks = agent spend, bids = repo languages, fills = latest pushes.
"""
import datetime

from common import LOGIN, compact, esc, gh_api, gh_graphql, money, write_svg

MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"

C = {
    "bg": "#070b10",
    "panel": "#0b1018",
    "border": "#1c2430",
    "grid": "#141b26",
    "dot": "#1a2330",
    "fg": "#9fb2c8",
    "muted": "#55657a",
    "mint": "#16c79a",
    "mintHi": "#97fce4",
    "red": "#f6465d",
    "amber": "#ffb454",
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

AGENT_TICKERS = {
    "claude": "CLAUDE", "codex": "CODEX", "droid": "DROID",
    "kimi": "KIMI", "opencode": "OPENCODE",
}

LANG_TICKER = {
    "TypeScript": "TS", "JavaScript": "JS", "Python": "PY", "Move": "MOVE",
    "Rust": "RS", "Solidity": "SOL", "HTML": "HTML", "Shell": "SH",
    "Jupyter Notebook": "IPYNB", "C++": "CPP", "Go": "GO", "Svelte": "SVLT",
    "Vue": "VUE", "C": "C",
}


def fetch_calendar():
    now = datetime.datetime.now(datetime.timezone.utc)
    frm = now - datetime.timedelta(days=364)
    cal = gh_graphql(
        QUERY,
        {"login": LOGIN, "from": frm.isoformat(), "to": now.isoformat()},
    )["user"]["contributionsCollection"]["contributionCalendar"]
    return cal


def fetch_fills():
    try:
        events = gh_api(f"/users/{LOGIN}/events/public?per_page=40")
    except Exception:
        return []
    now = datetime.datetime.now(datetime.timezone.utc)
    fills = []
    for e in events:
        if e["type"] != "PushEvent":
            continue
        dt = datetime.datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
        age = now - dt
        if age.days >= 1:
            ago = f"{age.days}d"
        elif age.seconds >= 3600:
            ago = f"{age.seconds // 3600}h"
        else:
            ago = f"{max(age.seconds // 60, 1)}m"
        fills.append(
            {"repo": e["repo"]["name"].split("/")[-1],
             "n": e["payload"].get("size", 1) or 1, "ago": ago}
        )
        if len(fills) == 4:
            break
    return fills


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
                {"o": seg[0], "c": seg[-1], "h": max(seg), "l": min(seg),
                 "v": sum(counts[idx:idx + k])}
            )
        idx += k
    candles = candles[-52:]

    agents = tokens["agents"]
    W, H = 940, 580
    head_h, tick_h = 44, 30
    chart_x, chart_y = 24, head_h + tick_h + 26
    chart_w, chart_h = 600, 300
    vol_h = 56
    panel_h = chart_h + vol_h + 46

    parts = []

    # ---- header ----------------------------------------------------------
    last_px = roll[-1] if roll else 0
    d30 = sum(counts[-30:])
    d30p = sum(counts[-60:-30]) or 1
    delta = 100 * (d30 - d30p) / d30p
    dcol = C["mint"] if delta >= 0 else C["red"]
    spend = tokens["totals"]["totalCost"]
    parts.append(
        f'<text x="{chart_x}" y="28" font-size="14" font-weight="700" fill="{C["mintHi"]}">'
        f'MAXMONEYCASH-PERP</text>'
        f'<text x="{chart_x + 178}" y="28" font-size="11" fill="{C["muted"]}">CONTRIB-7D / USD</text>'
        f'<circle cx="{chart_x + 300}" cy="24" r="4" fill="{C["mint"]}">'
        f'<animate attributeName="opacity" values="1;0.2;1" dur="2s" repeatCount="indefinite"/></circle>'
        f'<text x="{chart_x + 312}" y="28" font-size="11" fill="{C["mint"]}">LIVE</text>'
        f'<text x="{W - 24}" y="28" text-anchor="end" font-size="11" fill="{C["fg"]}">'
        f'LAST <tspan fill="{C["mintHi"]}" font-weight="700">{last_px}</tspan>'
        f'   30D <tspan fill="{dcol}" font-weight="700">{delta:+.1f}%</tspan>'
        f'   365D VOL <tspan fill="{C["mintHi"]}" font-weight="700">{total:,}</tspan>'
        f'   FUNDING <tspan fill="{C["amber"]}" font-weight="700">-{money(spend)}</tspan></text>'
    )

    # ---- language ticker marquee ----------------------------------------
    langs = sorted(gh["langs"].items(), key=lambda kv: -kv[1])[:8]
    lang_total = sum(v for _, v in langs) or 1
    cells, plain = [], ""
    for i, (lang, n) in enumerate(langs):
        sym = LANG_TICKER.get(lang, lang[:4].upper())
        pct = 100 * n / lang_total
        up = i % 3 != 2
        cells.append(
            f'<tspan fill="{C["fg"]}">{sym}</tspan>'
            f'<tspan fill="{C["mint"] if up else C["red"]}"> {pct:.1f}% {"▲" if up else "▼"}</tspan>'
            f'<tspan fill="{C["border"]}">   │   </tspan>'
        )
        plain += f"{sym} {pct:.1f}% X   |   "
    ticker_line = "".join(cells)
    tick_w = round(len(plain) * 6.6)
    parts.append(
        f'<g clip-path="url(#tickclip)"><g class="marquee">'
        f'<text x="0" y="{head_h + 20}" font-size="11">{ticker_line}{ticker_line}</text></g></g>'
    )

    # ---- chart panel: dot grid, fitted axis ------------------------------
    parts.append(
        f'<rect x="{chart_x - 4}" y="{chart_y - 14}" width="{chart_w + 60}" '
        f'height="{panel_h}" rx="8" fill="{C["panel"]}" stroke="{C["border"]}"/>'
        f'<rect x="{chart_x - 4}" y="{chart_y - 14}" width="{chart_w + 60}" '
        f'height="{panel_h}" rx="8" fill="url(#dots)"/>'
    )

    hi = max((c["h"] for c in candles), default=1)
    lo = min((c["l"] for c in candles), default=0)
    span = max(hi - lo, 1)
    hi += span * 0.06
    lo = max(lo - span * 0.05, 0)
    span = hi - lo

    def ys(v):
        return chart_y + chart_h * (1 - (v - lo) / span)

    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        v = lo + span * frac
        gy = ys(v)
        parts.append(
            f'<line x1="{chart_x + 4}" y1="{gy:.1f}" x2="{chart_x + chart_w}" y2="{gy:.1f}" '
            f'stroke="{C["grid"]}" stroke-dasharray="2 6"/>'
            f'<text x="{chart_x + chart_w + 10}" y="{gy + 4:.1f}" font-size="9" '
            f'fill="{C["muted"]}">{v:,.0f}</text>'
        )

    step = chart_w / max(len(candles), 1)
    body_w = max(step - 3, 2.5)

    # the line first…
    pts = " ".join(
        f"{chart_x + 6 + i * step + body_w / 2:.1f},{ys(c['c']):.1f}"
        for i, c in enumerate(candles)
    )
    parts.append(
        f'<polyline points="{pts}" fill="none" stroke="{C["mintHi"]}" '
        f'stroke-width="1" opacity="0.35"/>'
    )

    # …then candles around it
    vmax = max((c["v"] for c in candles), default=1) or 1
    for i, c in enumerate(candles):
        x = chart_x + 6 + i * step
        mid = x + body_w / 2
        up = c["c"] >= c["o"]
        color = C["mint"] if up else C["red"]
        top, bot = max(c["o"], c["c"]), min(c["o"], c["c"])
        parts.append(
            f'<line x1="{mid:.1f}" y1="{ys(c["h"]):.1f}" x2="{mid:.1f}" y2="{ys(c["l"]):.1f}" '
            f'stroke="{color}" stroke-width="1"/>'
            f'<rect x="{x:.1f}" y="{ys(top):.1f}" width="{body_w:.1f}" '
            f'height="{max(ys(bot) - ys(top), 2):.1f}" rx="1" fill="{color}"/>'
        )
        vy = chart_y + chart_h + 12
        vh = vol_h * c["v"] / vmax
        parts.append(
            f'<rect x="{x:.1f}" y="{vy + vol_h - vh:.1f}" width="{body_w:.1f}" '
            f'height="{max(vh, 1):.1f}" fill="{color}" opacity="0.4"/>'
        )

    # mark line at last close
    if candles:
        last_y = ys(candles[-1]["c"])
        parts.append(
            f'<line x1="{chart_x + 4}" y1="{last_y:.1f}" x2="{chart_x + chart_w}" y2="{last_y:.1f}" '
            f'stroke="{C["amber"]}" stroke-width="1" stroke-dasharray="6 4"/>'
            f'<rect x="{chart_x + chart_w + 4}" y="{last_y - 9:.1f}" width="50" height="17" rx="3" fill="{C["amber"]}"/>'
            f'<text x="{chart_x + chart_w + 29}" y="{last_y + 4:.1f}" text-anchor="middle" '
            f'font-size="10" font-weight="700" fill="#070b10">{candles[-1]["c"]}</text>'
        )

    # month labels along the bottom
    seen = set()
    idx = 0
    for wi, w in enumerate(cal["weeks"][-52:]):
        d0 = w["contributionDays"][0]["date"]
        mon = datetime.date.fromisoformat(d0).strftime("%b")
        if mon not in seen and wi % 4 == 0:
            seen.add(mon)
            parts.append(
                f'<text x="{chart_x + 6 + wi * step:.1f}" y="{chart_y + chart_h + vol_h + 26}" '
                f'font-size="9" fill="{C["muted"]}">{mon.upper()}</text>'
            )

    # ---- order book + fills ----------------------------------------------
    ob_x, ob_w = chart_x + chart_w + 76, W - chart_x - chart_w - 100
    ob_y = chart_y - 14
    row_h = 22
    parts.append(
        f'<rect x="{ob_x}" y="{ob_y}" width="{ob_w}" height="{panel_h}" rx="8" '
        f'fill="{C["panel"]}" stroke="{C["border"]}"/>'
        f'<text x="{ob_x + 14}" y="{ob_y + 24}" font-size="11" letter-spacing="2" '
        f'fill="{C["fg"]}">ORDER BOOK</text>'
        f'<text x="{ob_x + ob_w - 14}" y="{ob_y + 24}" text-anchor="end" font-size="9" '
        f'fill="{C["muted"]}">AGENTS × LANGS</text>'
    )
    asks = sorted(agents.items(), key=lambda kv: kv[1]["totals"].get("totalCost") or 0)
    amax = max((a[1]["totals"].get("totalCost") or 1) for a in asks)
    ay = ob_y + 38
    for name, a in asks:
        cost = a["totals"].get("totalCost") or 0
        tok = a["totals"].get("totalTokens") or 0
        bw = (ob_w - 28) * cost / amax
        parts.append(
            f'<rect x="{ob_x + ob_w - 14 - bw:.1f}" y="{ay}" width="{bw:.1f}" height="{row_h - 5}" '
            f'fill="{C["red"]}" opacity="0.16"/>'
            f'<text x="{ob_x + 14}" y="{ay + 12}" font-size="10" fill="{C["red"]}">{AGENT_TICKERS[name]}</text>'
            f'<text x="{ob_x + ob_w - 14}" y="{ay + 12}" text-anchor="end" font-size="10" '
            f'fill="{C["fg"]}">{money(cost)} <tspan fill="{C["muted"]}">· {compact(tok)}</tspan></text>'
        )
        ay += row_h
    parts.append(
        f'<line x1="{ob_x + 10}" y1="{ay + 3}" x2="{ob_x + ob_w - 10}" y2="{ay + 3}" stroke="{C["border"]}"/>'
        f'<text x="{ob_x + ob_w / 2}" y="{ay + 19}" text-anchor="middle" font-size="11" '
        f'font-weight="700" fill="{C["amber"]}">MARK {compact(tokens["totals"]["totalTokens"])} TOK</text>'
        f'<line x1="{ob_x + 10}" y1="{ay + 27}" x2="{ob_x + ob_w - 10}" y2="{ay + 27}" stroke="{C["border"]}"/>'
    )
    by = ay + 40
    bmax = max((n for _, n in langs[:5]), default=1)
    for lang, n in langs[:5]:
        sym = LANG_TICKER.get(lang, lang[:4].upper())
        bw = (ob_w - 28) * n / bmax
        parts.append(
            f'<rect x="{ob_x + 14}" y="{by}" width="{bw:.1f}" height="{row_h - 5}" '
            f'fill="{C["mint"]}" opacity="0.16"/>'
            f'<text x="{ob_x + 14}" y="{by + 12}" font-size="10" fill="{C["mint"]}">{esc(sym)}</text>'
            f'<text x="{ob_x + ob_w - 14}" y="{by + 12}" text-anchor="end" font-size="10" '
            f'fill="{C["fg"]}">{n} repos</text>'
        )
        by += row_h

    fills = fetch_fills()
    if fills:
        fy = by + 14
        parts.append(
            f'<line x1="{ob_x + 10}" y1="{fy - 8}" x2="{ob_x + ob_w - 10}" y2="{fy - 8}" stroke="{C["border"]}"/>'
            f'<text x="{ob_x + 14}" y="{fy + 6}" font-size="10" letter-spacing="2" '
            f'fill="{C["muted"]}">RECENT FILLS</text>'
        )
        fy += 22
        for f_ in fills:
            label = f_["repo"][:16]
            parts.append(
                f'<text x="{ob_x + 14}" y="{fy}" font-size="9.5" fill="{C["mint"]}">BUY '
                f'<tspan fill="{C["fg"]}">{esc(label)}</tspan></text>'
                f'<text x="{ob_x + ob_w - 14}" y="{fy}" text-anchor="end" font-size="9.5" '
                f'fill="{C["muted"]}">{f_["n"]}c · {f_["ago"]}</text>'
            )
            fy += 18

    # ---- stats strip -------------------------------------------------------
    cur, peak = streaks(counts)
    active = sum(1 for c in counts if c > 0)
    ath = max((c["v"] for c in candles), default=0)
    sy = chart_y - 14 + panel_h + 28
    parts.append(
        f'<text x="{chart_x}" y="{sy}" font-size="11" fill="{C["muted"]}">'
        f'ATH WEEK <tspan fill="{C["mintHi"]}" font-weight="700">{ath}</tspan>'
        f'   ACTIVE DAYS <tspan fill="{C["mintHi"]}" font-weight="700">{active}/365</tspan>'
        f'   STREAK <tspan fill="{C["mint"]}" font-weight="700">{cur}D</tspan>'
        f'   PEAK STREAK <tspan fill="{C["mint"]}" font-weight="700">{peak}D</tspan>'
        f'   30D VOL <tspan fill="{C["mintHi"]}" font-weight="700">{d30}</tspan>'
        f'   1W CANDLES ON A 7D ROLLING INDEX</text>'
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <clipPath id="tickclip"><rect x="{chart_x}" y="{head_h}" width="{W - 48}" height="{tick_h}"/></clipPath>
  <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">
    <circle cx="2" cy="2" r="0.9" fill="{C['dot']}"/>
  </pattern>
  <style>
    @keyframes tick {{ from {{ transform: translateX({chart_x}px); }} to {{ transform: translateX({chart_x - tick_w}px); }} }}
    .marquee {{ animation: tick 36s linear infinite; }}
  </style>
</defs>
<rect width="{W}" height="{H}" rx="14" fill="{C['bg']}" stroke="{C['border']}"/>
<line x1="0" y1="{head_h}" x2="{W}" y2="{head_h}" stroke="{C['border']}"/>
<line x1="0" y1="{head_h + tick_h}" x2="{W}" y2="{head_h + tick_h}" stroke="{C['border']}"/>
{"".join(parts)}
</svg>"""
    write_svg("market.svg", svg)
