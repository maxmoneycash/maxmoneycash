"""Perps-terminal dashboard: contributions as candles, agents/langs as an order book.

Bloomberg/Hyperliquid-styled, but the data is all real: weekly contribution
OHLC from the GitHub GraphQL calendar, volume = weekly totals, asks = agent
spend, bids = repo languages.
"""
import datetime

from common import LOGIN, compact, esc, gh_graphql, money, write_svg

MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"

C = {
    "bg": "#070b10",
    "panel": "#0b1018",
    "border": "#1c2430",
    "grid": "#141b26",
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
}


def fetch_weeks():
    now = datetime.datetime.now(datetime.timezone.utc)
    frm = now - datetime.timedelta(days=364)
    cal = gh_graphql(
        QUERY,
        {"login": LOGIN, "from": frm.isoformat(), "to": now.isoformat()},
    )["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = []
    for w in cal["weeks"]:
        counts = [d["contributionCount"] for d in w["contributionDays"]]
        if counts:
            weeks.append(
                {"o": counts[0], "c": counts[-1], "h": max(counts),
                 "l": min(counts), "v": sum(counts)}
            )
    return weeks, cal["totalContributions"]


def render(gh, tokens):
    weeks, total = fetch_weeks()
    weeks = weeks[-52:]
    agents = tokens["agents"]

    W, H = 940, 470
    head_h, tick_h = 44, 30
    chart_x, chart_y = 24, head_h + tick_h + 26
    chart_w, chart_h = 600, 250
    vol_h = 56

    parts = []

    # ---- header ----------------------------------------------------------
    this_week = weeks[-1]["v"] if weeks else 0
    spend = tokens["totals"]["totalCost"]
    parts.append(
        f'<text x="{chart_x}" y="28" font-size="14" font-weight="700" fill="{C["mintHi"]}">'
        f'MAXMONEYCASH-PERP</text>'
        f'<text x="{chart_x + 178}" y="28" font-size="11" fill="{C["muted"]}">CONTRIB / USD</text>'
        f'<circle cx="{chart_x + 280}" cy="24" r="4" fill="{C["mint"]}">'
        f'<animate attributeName="opacity" values="1;0.2;1" dur="2s" repeatCount="indefinite"/></circle>'
        f'<text x="{chart_x + 292}" y="28" font-size="11" fill="{C["mint"]}">LIVE</text>'
        f'<text x="{W - 24}" y="28" text-anchor="end" font-size="11" fill="{C["fg"]}">'
        f'LAST <tspan fill="{C["mintHi"]}" font-weight="700">{this_week}</tspan>'
        f'   365D VOL <tspan fill="{C["mintHi"]}" font-weight="700">{total:,}</tspan>'
        f'   FUNDING <tspan fill="{C["amber"]}" font-weight="700">-{money(spend)}</tspan></text>'
    )

    # ---- language ticker marquee ----------------------------------------
    langs = sorted(gh["langs"].items(), key=lambda kv: -kv[1])[:8]
    lang_total = sum(v for _, v in langs) or 1
    cells = []
    for i, (lang, n) in enumerate(langs):
        sym = LANG_TICKER.get(lang, lang[:4].upper())
        pct = 100 * n / lang_total
        up = i % 3 != 2
        cells.append(
            f'<tspan fill="{C["fg"]}">{sym}</tspan>'
            f'<tspan fill="{C["mint"] if up else C["red"]}"> {pct:.1f}% {"▲" if up else "▼"}</tspan>'
            f'<tspan fill="{C["border"]}">   │   </tspan>'
        )
    ticker_line = "".join(cells)
    plain = ""
    for i, (lang, n) in enumerate(langs):
        sym = LANG_TICKER.get(lang, lang[:4].upper())
        pct = 100 * n / lang_total
        plain += f"{sym} {pct:.1f}% X   |   "
    tick_w = round(len(plain) * 6.6)  # one copy's width; shift by this for a seamless loop
    ty = head_h + 20
    parts.append(
        f'<g clip-path="url(#tickclip)"><g class="marquee">'
        f'<text x="0" y="{ty}" font-size="11">{ticker_line}{ticker_line}</text></g></g>'
    )

    # ---- candles ----------------------------------------------------------
    hi = max((w["h"] for w in weeks), default=1) or 1
    parts.append(
        f'<rect x="{chart_x - 4}" y="{chart_y - 14}" width="{chart_w + 60}" '
        f'height="{chart_h + vol_h + 44}" rx="8" fill="{C["panel"]}" stroke="{C["border"]}"/>'
    )
    for frac in (0.25, 0.5, 0.75, 1.0):
        gy = chart_y + chart_h * (1 - frac)
        parts.append(
            f'<line x1="{chart_x + 4}" y1="{gy:.1f}" x2="{chart_x + chart_w}" y2="{gy:.1f}" '
            f'stroke="{C["grid"]}" stroke-dasharray="3 5"/>'
            f'<text x="{chart_x + chart_w + 8}" y="{gy + 4:.1f}" font-size="9" '
            f'fill="{C["muted"]}">{hi * frac:.0f}</text>'
        )
    step = chart_w / max(len(weeks), 1)
    body_w = max(step - 3.5, 2.5)
    vmax = max((w["v"] for w in weeks), default=1) or 1
    for i, wk in enumerate(weeks):
        x = chart_x + 6 + i * step
        mid = x + body_w / 2
        up = wk["c"] >= wk["o"]
        color = C["mint"] if up else C["red"]
        ys = lambda v: chart_y + chart_h * (1 - v / hi)
        top, bot = max(wk["o"], wk["c"]), min(wk["o"], wk["c"])
        parts.append(
            f'<line x1="{mid:.1f}" y1="{ys(wk["h"]):.1f}" x2="{mid:.1f}" y2="{ys(wk["l"]):.1f}" '
            f'stroke="{color}" stroke-width="1"/>'
            f'<rect x="{x:.1f}" y="{ys(top):.1f}" width="{body_w:.1f}" '
            f'height="{max(ys(bot) - ys(top), 1.5):.1f}" rx="1" fill="{color}"/>'
        )
        vy = chart_y + chart_h + 14
        vh = vol_h * wk["v"] / vmax
        parts.append(
            f'<rect x="{x:.1f}" y="{vy + vol_h - vh:.1f}" width="{body_w:.1f}" '
            f'height="{max(vh, 1):.1f}" fill="{color}" opacity="0.45"/>'
        )

    # mark line at last close
    if weeks:
        last_y = chart_y + chart_h * (1 - weeks[-1]["c"] / hi)
        parts.append(
            f'<line x1="{chart_x + 4}" y1="{last_y:.1f}" x2="{chart_x + chart_w}" y2="{last_y:.1f}" '
            f'stroke="{C["amber"]}" stroke-width="1" stroke-dasharray="6 4"/>'
            f'<rect x="{chart_x + chart_w + 2}" y="{last_y - 9:.1f}" width="52" height="16" rx="3" fill="{C["amber"]}"/>'
            f'<text x="{chart_x + chart_w + 28}" y="{last_y + 3:.1f}" text-anchor="middle" '
            f'font-size="10" font-weight="700" fill="#070b10">MARK</text>'
        )
    parts.append(
        f'<text x="{chart_x + 6}" y="{chart_y + chart_h + vol_h + 26}" font-size="10" '
        f'fill="{C["muted"]}">CONTRIBUTIONS · 1W CANDLES · O/H/L/C = first/max/min/last day of week · VOL = weekly total</text>'
    )

    # ---- order book -------------------------------------------------------
    ob_x, ob_w = chart_x + chart_w + 76, W - chart_x - chart_w - 100
    ob_y = chart_y - 14
    row_h = 24
    parts.append(
        f'<rect x="{ob_x}" y="{ob_y}" width="{ob_w}" height="{chart_h + vol_h + 44}" rx="8" '
        f'fill="{C["panel"]}" stroke="{C["border"]}"/>'
        f'<text x="{ob_x + 14}" y="{ob_y + 24}" font-size="11" letter-spacing="2" '
        f'fill="{C["fg"]}">ORDER BOOK</text>'
        f'<text x="{ob_x + ob_w - 14}" y="{ob_y + 24}" text-anchor="end" font-size="9" '
        f'fill="{C["muted"]}">AGENTS × LANGS</text>'
    )

    # asks: agents by spend (red, top)
    asks = sorted(
        agents.items(), key=lambda kv: kv[1]["totals"].get("totalCost") or 0
    )
    amax = max((a[1]["totals"].get("totalCost") or 1) for a in asks)
    ay = ob_y + 40
    for name, a in asks:
        cost = a["totals"].get("totalCost") or 0
        tok = a["totals"].get("totalTokens") or 0
        bw = (ob_w - 28) * cost / amax
        parts.append(
            f'<rect x="{ob_x + ob_w - 14 - bw:.1f}" y="{ay}" width="{bw:.1f}" height="{row_h - 6}" '
            f'fill="{C["red"]}" opacity="0.16"/>'
            f'<text x="{ob_x + 14}" y="{ay + 13}" font-size="10" fill="{C["red"]}">{AGENT_TICKERS[name]}</text>'
            f'<text x="{ob_x + ob_w - 14}" y="{ay + 13}" text-anchor="end" font-size="10" '
            f'fill="{C["fg"]}">{money(cost)} <tspan fill="{C["muted"]}">· {compact(tok)}</tspan></text>'
        )
        ay += row_h
    # spread / mark
    parts.append(
        f'<line x1="{ob_x + 10}" y1="{ay + 4}" x2="{ob_x + ob_w - 10}" y2="{ay + 4}" stroke="{C["border"]}"/>'
        f'<text x="{ob_x + ob_w / 2}" y="{ay + 22}" text-anchor="middle" font-size="11" '
        f'font-weight="700" fill="{C["amber"]}">MARK {compact(tokens["totals"]["totalTokens"])} TOK</text>'
        f'<line x1="{ob_x + 10}" y1="{ay + 32}" x2="{ob_x + ob_w - 10}" y2="{ay + 32}" stroke="{C["border"]}"/>'
    )
    # bids: languages by repo count (green, bottom)
    by = ay + 46
    bmax = max((n for _, n in langs[:5]), default=1)
    for lang, n in langs[:5]:
        sym = LANG_TICKER.get(lang, lang[:4].upper())
        bw = (ob_w - 28) * n / bmax
        parts.append(
            f'<rect x="{ob_x + 14}" y="{by}" width="{bw:.1f}" height="{row_h - 6}" '
            f'fill="{C["mint"]}" opacity="0.16"/>'
            f'<text x="{ob_x + 14}" y="{by + 13}" font-size="10" fill="{C["mint"]}">{esc(sym)}</text>'
            f'<text x="{ob_x + ob_w - 14}" y="{by + 13}" text-anchor="end" font-size="10" '
            f'fill="{C["fg"]}">{n} repos</text>'
        )
        by += row_h

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <clipPath id="tickclip"><rect x="{chart_x}" y="{head_h}" width="{W - 48}" height="{tick_h}"/></clipPath>
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
