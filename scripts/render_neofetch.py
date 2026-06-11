"""Neofetch-style hero card: rainbow Apple ASCII + live GitHub/token stats."""
import datetime

from common import (
    APPLE_STRIPES,
    THEME,
    compact,
    esc,
    money,
    write_svg,
)

APPLE_ASCII = """\
                    'c.
                 ,xNMM.
               .OMMMMo
               OMMM0,
     .;loddo:' loolloddol;.
   cKMMMMMMMMMMNWMMMMMMMMMM0:
 .KMMMMMMMMMMMMMMMMMMMMMMMWd.
 XMMMMMMMMMMMMMMMMMMMMMMMX.
;MMMMMMMMMMMMMMMMMMMMMMMM:
:MMMMMMMMMMMMMMMMMMMMMMMM:
.MMMMMMMMMMMMMMMMMMMMMMMMX.
 kMMMMMMMMMMMMMMMMMMMMMMMMWd.
 .XMMMMMMMMMMMMMMMMMMMMMMMMMMk
  .XMMMMMMMMMMMMMMMMMMMMMMMMK.
    kMMMMMMMMMMMMMMMMMMMMMMd
     ;KMMMMMMMWXXWMMMMMMMk.
       .cooc,.    .,coo:.""".split("\n")

# Leaf is green like the real logo; the body sweeps the six stripes.
ROW_STRIPE = [0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 5]

MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"


def _ascii_block(x, y, line_h, size, extra=""):
    rows = []
    for i, line in enumerate(APPLE_ASCII):
        color = APPLE_STRIPES[ROW_STRIPE[i]]
        rows.append(
            f'<text x="{x}" y="{y + i * line_h}" font-size="{size}" '
            f'fill="{color}" xml:space="preserve"{extra}>{esc(line)}</text>'
        )
    return "\n".join(rows)


def render(gh, tokens):
    t = THEME
    user = gh["user"]
    created = datetime.datetime.fromisoformat(user["created_at"].replace("Z", "+00:00"))
    now = datetime.datetime.now(datetime.timezone.utc)
    months_total = (now.year - created.year) * 12 + now.month - created.month
    uptime = f"{months_total // 12} years, {months_total % 12} months"

    totals = tokens["totals"]
    agents = tokens["agents"]

    W = 940
    ascii_x, ascii_y, line_h = 42, 92, 15

    info_x = 370
    info_lh = 19
    info_y = 88
    kv = [
        ("OS", "macOS arm64 (Darwin 25.2)"),
        ("Host", "github.com/maxmoneycash"),
        ("Kernel", "vibe-driven development"),
        ("Uptime", f"{uptime} on GitHub"),
        ("Packages", f"{user['public_repos']} repos (gh), {gh['stars']} stars"),
        ("Shell", "zsh + 6 coding agents"),
        ("Agents", "claude / codex / kimi / opencode / droid / cursor"),
        ("CPU", f"Claude (Anthropic) — {compact(agents['claude']['totals']['totalTokens'])} tok"),
        ("GPU", f"Codex (OpenAI) — {compact(agents['codex']['totals']['totalTokens'])} tok"),
        ("Memory", f"{compact(totals['cacheReadTokens'])} cache-read tokens"),
        ("Disk", f"{compact(totals['totalTokens'])} tokens all-time"),
        ("Battery", f"{money(totals['totalCost'])} burned, still at 100%"),
    ]

    rows = [
        f'<text x="{info_x}" y="{info_y}" font-size="14" font-weight="700" '
        f'fill="{t["phosphor"]}" filter="url(#soft)">maxmoneycash'
        f'<tspan fill="{t["muted"]}">@</tspan><tspan fill="{t["value"]}">github</tspan></text>',
        f'<text x="{info_x}" y="{info_y + info_lh}" font-size="13" fill="{t["border"]}" '
        f'xml:space="preserve">{"-" * 34}</text>',
    ]
    for i, (k, v) in enumerate(kv):
        y = info_y + (i + 2) * info_lh
        rows.append(
            f'<g font-size="13"><text x="{info_x}" y="{y}" fill="{t["key"]}" '
            f'font-weight="600">{esc(k)}</text>'
            f'<text x="{info_x + 86}" y="{y}" fill="{t["fg"]}">{esc(v)}</text></g>'
        )

    dots_y = info_y + (len(kv) + 2) * info_lh + 10
    dots = "".join(
        f'<circle cx="{info_x + 10 + i * 26}" cy="{dots_y}" r="8" '
        f'fill="{c}" class="pulse" style="animation-delay:{i * 0.15:.2f}s"/>'
        for i, c in enumerate(APPLE_STRIPES + ["#c9d1d9", "#8b949e"])
    )

    prompt_y = 412
    chips_y = 432
    chip_w, chip_h, gap = 199, 80, 16
    chips = [
        ("TOKENS ALL-TIME", compact(totals["totalTokens"]), t["phosphor"]),
        ("COMPUTE BURNED", money(totals["totalCost"]), t["amber"]),
        ("PUBLIC REPOS", str(user["public_repos"]), t["value"]),
        ("FOLLOWERS", str(user["followers"]), APPLE_STRIPES[4]),
    ]
    # Boxless stat row: big glowing numbers over letter-spaced labels, with a
    # short accent tick above each and hairline dividers between columns.
    chip_svg = []
    for i, (label, value, color) in enumerate(chips):
        cx = 42 + i * (chip_w + gap)
        mid = cx + chip_w / 2
        chip_svg.append(
            f'<g><rect x="{mid - 16}" y="{chips_y + 2}" width="32" height="3" rx="1.5" fill="{color}"/>'
            f'<text x="{mid}" y="{chips_y + 44}" text-anchor="middle" '
            f'font-size="30" font-weight="700" fill="{color}">{esc(value)}</text>'
            f'<text x="{mid}" y="{chips_y + 66}" text-anchor="middle" '
            f'font-size="11" letter-spacing="1.5" fill="{t["fg"]}">{esc(label)}</text></g>'
        )
        if i:
            chip_svg.append(
                f'<line x1="{cx - gap / 2}" y1="{chips_y + 8}" x2="{cx - gap / 2}" '
                f'y2="{chips_y + 62}" stroke="{t["border"]}"/>'
            )

    H = chips_y + chip_h + 28

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{t['bg']}"/><stop offset="1" stop-color="{t['bg2']}"/>
  </linearGradient>
  <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
    <feGaussianBlur stdDeviation="2.6"/>
  </filter>
  <filter id="soft" x="-30%" y="-30%" width="160%" height="160%">
    <feGaussianBlur stdDeviation="1.4" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">
    <rect width="4" height="2" fill="#000" opacity="0.16"/>
  </pattern>
  <radialGradient id="vig" cx="0.5" cy="0.45" r="0.85">
    <stop offset="0.62" stop-color="#000" stop-opacity="0"/>
    <stop offset="1" stop-color="#000" stop-opacity="0.32"/>
  </radialGradient>
  <style>
    @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.45; }} }}
    .pulse {{ animation: pulse 2.4s ease-in-out infinite; }}
    @keyframes blink {{ 0%,49% {{ opacity: 1; }} 50%,100% {{ opacity: 0; }} }}
    .cursor {{ animation: blink 1.1s step-end infinite; }}
  </style>
</defs>
<rect width="{W}" height="{H}" rx="14" fill="url(#bg)" stroke="{t['border']}"/>
<circle cx="26" cy="26" r="7" fill="#ff5f56"/><circle cx="48" cy="26" r="7" fill="#ffbd2e"/><circle cx="70" cy="26" r="7" fill="#27c93f"/>
<text x="{W / 2}" y="31" text-anchor="middle" font-size="13" fill="{t['muted']}">max@maxmoneycash: ~/neofetch</text>
<line x1="0" y1="46" x2="{W}" y2="46" stroke="{t['border']}"/>
<g opacity="0.55">{_ascii_block(ascii_x, ascii_y, line_h, 13, ' filter="url(#glow)"')}</g>
{_ascii_block(ascii_x, ascii_y, line_h, 13)}
{"".join(rows)}
{dots}
<text x="42" y="{prompt_y}" font-size="13" fill="{t['muted']}">~ <tspan fill="{t['phosphor']}">❯</tspan> <tspan fill="{t['fg']}">ccusage --all-time --agents claude,codex,kimi,opencode,droid</tspan><tspan class="cursor" fill="{t['phosphor']}">▍</tspan></text>
{"".join(chip_svg)}
<rect width="{W}" height="{H}" rx="14" fill="url(#scan)"/>
<rect width="{W}" height="{H}" rx="14" fill="url(#vig)"/>
</svg>"""
    write_svg("neofetch.svg", svg)
