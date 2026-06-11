"""Year-in-tokens wrapped card: 1200x630 editorial share card for X."""
import datetime

from common import (
    AGENT_COLORS,
    AGENT_LABELS,
    THEME,
    compact,
    esc,
    money,
    write_svg,
)

MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"
CURSOR_COLOR = "#e3e9f0"

W, H = 1200, 630


def render(gh, tokens):
    t = THEME
    totals = tokens["totals"]
    agents = tokens["agents"]
    first = datetime.datetime.strptime(tokens["monthly"][0]["period"], "%Y-%m")
    last = datetime.datetime.strptime(tokens["monthly"][-1]["period"], "%Y-%m")
    now = datetime.datetime.now(datetime.timezone.utc)

    total_str = f"{totals['totalTokens']:,}"
    novels = totals["outputTokens"] * 0.75 / 90_000
    cache_pct = 100 * totals["cacheReadTokens"] / totals["totalTokens"]
    n_models = len({
        b["modelName"] for m in tokens["monthly"] for b in m["modelBreakdowns"]
    })

    parts = []

    # masthead
    period = f"{first:%b %Y} — {last:%b %Y}".upper()
    parts.append(
        f'<text x="70" y="84" font-size="15" letter-spacing="6" fill="{t["muted"]}">MAXMONEYCASH · ANNUAL COMPUTE REPORT</text>'
        f'<text x="70" y="146" font-size="44" font-weight="700" fill="{t["fg"]}">YEAR IN <tspan fill="{t["phosphor"]}">TOKENS</tspan></text>'
        f'<text x="{W - 70}" y="84" text-anchor="end" font-size="13" fill="{t["amber"]}">{period}</text>'
    )

    # hero number
    size = min(96, int((W - 140) / (len(total_str) * 0.62)))
    parts.append(
        f'<text x="{W / 2}" y="276" text-anchor="middle" font-size="{size}" '
        f'font-weight="700" fill="{t["phosphor"]}">{total_str}</text>'
        f'<text x="{W / 2}" y="316" text-anchor="middle" font-size="15" letter-spacing="4" '
        f'fill="{t["muted"]}">TOKENS ACROSS SIX CODING AGENTS · {esc(money(totals["totalCost"]))} BURNED</text>'
    )

    # agent split stacked bar
    bar_x, bar_y, bar_w, bar_h = 70, 366, W - 140, 30
    order = sorted(
        agents.items(), key=lambda kv: -(kv[1]["totals"].get("totalTokens") or 0)
    )
    x = bar_x
    grand = totals["totalTokens"] or 1
    for name, a in order:
        v = a["totals"].get("totalTokens") or 0
        if not v:
            continue
        w = bar_w * v / grand
        color = AGENT_COLORS.get(name, CURSOR_COLOR)
        parts.append(
            f'<rect x="{x:.1f}" y="{bar_y}" width="{max(w - 2, 1):.1f}" height="{bar_h}" rx="4" fill="{color}"/>'
        )
        if w > 88:
            parts.append(
                f'<text x="{x + 8:.1f}" y="{bar_y + 20}" font-size="11" font-weight="700" '
                f'fill="#070b10">{AGENT_LABELS[name]} {compact(v)}</text>'
            )
        x += w
    legend_x = bar_x
    for name, a in order:
        v = a["totals"].get("totalTokens") or 0
        if not v:
            continue
        color = AGENT_COLORS.get(name, CURSOR_COLOR)
        label = f"{AGENT_LABELS[name]} {100 * v / grand:.0f}%"
        parts.append(
            f'<circle cx="{legend_x + 5}" cy="{bar_y + 52}" r="5" fill="{color}"/>'
            f'<text x="{legend_x + 16}" y="{bar_y + 56}" font-size="11" fill="{t["fg"]}">{label}</text>'
        )
        legend_x += 16 + len(label) * 7 + 26

    # stat columns
    stats = [
        ("OUTPUT WRITTEN", compact(totals["outputTokens"]), f"≈ {novels:,.0f} novels"),
        ("CACHE HIT RATE", f"{cache_pct:.1f}%", "context re-reads"),
        ("MODELS USED", str(n_models), "claude · gpt · kimi · glm +"),
        ("AVG / MONTH", money(totals["totalCost"] / max(len(tokens["monthly"]), 1)), "every month, all year"),
    ]
    col_w = (W - 140) / 4
    for i, (label, value, sub) in enumerate(stats):
        cx = 70 + i * col_w + col_w / 2
        parts.append(
            f'<text x="{cx}" y="{510}" text-anchor="middle" font-size="34" font-weight="700" '
            f'fill="{t["amber"] if i % 2 else t["phosphor"]}">{esc(value)}</text>'
            f'<text x="{cx}" y="{533}" text-anchor="middle" font-size="10" letter-spacing="2" '
            f'fill="{t["muted"]}">{esc(label)}</text>'
            f'<text x="{cx}" y="{550}" text-anchor="middle" font-size="10" fill="{t["fg"]}" '
            f'opacity="0.75">{esc(sub)}</text>'
        )
        if i:
            parts.append(
                f'<line x1="{70 + i * col_w}" y1="478" x2="{70 + i * col_w}" y2="552" stroke="{t["border"]}"/>'
            )

    parts.append(
        f'<line x1="70" y1="582" x2="{W - 70}" y2="582" stroke="{t["border"]}"/>'
        f'<text x="70" y="606" font-size="11" fill="{t["muted"]}">github.com/maxmoneycash</text>'
        f'<text x="{W - 70}" y="606" text-anchor="end" font-size="11" fill="{t["muted"]}">'
        f'audited from raw agent logs · rendered {now:%Y-%m-%d}</text>'
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <linearGradient id="wbg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#0a0f17"/><stop offset="1" stop-color="#070b10"/>
  </linearGradient>
  <pattern id="wdots" width="26" height="26" patternUnits="userSpaceOnUse">
    <circle cx="2" cy="2" r="1" fill="#16202c"/>
  </pattern>
</defs>
<rect width="{W}" height="{H}" fill="url(#wbg)"/>
<rect width="{W}" height="{H}" fill="url(#wdots)"/>
<rect x="14" y="14" width="{W - 28}" height="{H - 28}" fill="none" stroke="{t['border']}" stroke-width="1.5"/>
{"".join(parts)}
</svg>"""
    write_svg("wrapped.svg", svg)
