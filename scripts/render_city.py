"""Isometric contribution city: a year of GitHub contributions as buildings
with window skins, set against a San Francisco skyline at dusk.

Replaces yoshi389111/github-profile-3d-contrib so we control the scene.
Still reads as a contribution graph: 53 weeks x 7 days, green intensity ramp.
"""
import datetime

from common import LOGIN, gh_graphql, write_svg

MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"

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

# top / left / right face colors per intensity level (mint ramp at dusk)
FACES = [
    ("#10171f", "#0d141b", "#0a1016"),
    ("#0d4f43", "#0a3a32", "#072a24"),
    ("#0f8a6e", "#0b6852", "#084d3d"),
    ("#16c79a", "#109573", "#0b6b53"),
    ("#97fce4", "#5fd9bd", "#3aa78f"),
]
HEIGHTS = [2, 16, 30, 46, 64]

SKY_TOP = "#05080f"
SKY_MID = "#0a1220"
HORIZON = "#0e1a2b"
SIL = "#121b29"      # skyline silhouette
SIL_LIT = "#1a2334"  # lighter foreground silhouette
WIN_LIT = "#ffd479"
WIN_DARK = "#0a1119"
AMBER = "#ffb454"
MINT = "#16c79a"
MINT_HI = "#97fce4"
FG = "#9fb2c8"
MUTED = "#55657a"
BORDER = "#1c2430"

W, H = 940, 570
HORIZON_Y = 196


def _skyline():
    """SF silhouette: Golden Gate, Sutro, Coit, Transamerica, Salesforce."""
    s = []
    base = HORIZON_Y

    def box(x, w, h, color=SIL):
        s.append(f'<rect x="{x}" y="{base - h}" width="{w}" height="{h}" fill="{color}"/>')

    # Golden Gate bridge (left): deck, two towers with crossbars, cables
    s.append(f'<rect x="18" y="{base - 36}" width="240" height="4" fill="{SIL_LIT}"/>')
    for tx in (62, 188):
        s.append(f'<rect x="{tx}" y="{base - 96}" width="7" height="96" fill="{SIL_LIT}"/>')
        for cy in (base - 88, base - 66, base - 46):
            s.append(f'<rect x="{tx - 4}" y="{cy}" width="15" height="3.5" fill="{SIL_LIT}"/>')
    s.append(
        f'<path d="M 18 {base - 60} Q 65 {base - 96} 125 {base - 50} '
        f'Q 190 {base - 96} 258 {base - 58}" fill="none" stroke="{SIL_LIT}" stroke-width="2"/>'
    )
    for vx in range(34, 250, 16):
        s.append(f'<line x1="{vx}" y1="{base - 36}" x2="{vx}" y2="{base - 72}" stroke="{SIL_LIT}" stroke-width="0.8" opacity="0.7"/>')

    # mid-city boxes
    box(286, 26, 38)
    box(316, 20, 52)
    box(340, 30, 30)
    # Coit tower
    s.append(f'<rect x="384" y="{base - 58}" width="10" height="58" fill="{SIL}"/>')
    s.append(f'<rect x="381" y="{base - 64}" width="16" height="8" fill="{SIL}"/>')
    box(402, 24, 34)
    # Transamerica pyramid
    s.append(f'<polygon points="452,{base} 464,{base - 110} 476,{base}" fill="{SIL}"/>')
    s.append(f'<rect x="462" y="{base - 122}" width="4" height="14" fill="{SIL}"/>')
    box(484, 28, 46)
    box(516, 22, 64)
    # Salesforce tower (rounded top)
    s.append(
        f'<path d="M 548 {base} L 548 {base - 124} Q 566 {base - 138} 584 {base - 124} '
        f'L 584 {base} Z" fill="{SIL}"/>'
    )
    box(592, 26, 56)
    box(622, 32, 40)
    box(658, 22, 70)
    box(684, 28, 48)
    box(716, 24, 30)
    # Sutro tower (right, on a hill)
    s.append(f'<path d="M 760 {base} Q 810 {base - 40} 870 {base}" fill="{SIL}"/>')
    for off in (-18, 0, 18):
        s.append(
            f'<line x1="{822 + off}" y1="{base - 30}" x2="{822 + off * 0.4:.0f}" '
            f'y2="{base - 118}" stroke="{SIL_LIT}" stroke-width="3"/>'
        )
    s.append(f'<rect x="806" y="{base - 96}" width="33" height="4" fill="{SIL_LIT}"/>')
    s.append(f'<rect x="810" y="{base - 70}" width="25" height="4" fill="{SIL_LIT}"/>')
    box(880, 26, 36)
    box(910, 18, 24)

    # lit windows sprinkled on the towers (deterministic)
    for i in range(90):
        bx = (i * 137) % 900 + 20
        byy = base - 8 - (i * 53) % 100
        if 280 < bx < 740 and byy > base - 115:
            lit = (i * 7) % 3 == 0
            s.append(
                f'<rect x="{bx}" y="{byy}" width="1.6" height="2.4" '
                f'fill="{WIN_LIT if lit else "#243043"}" opacity="{0.9 if lit else 0.5}"/>'
            )
    return "".join(s)


def _level(count, q):
    if count <= 0:
        return 0
    for i, t in enumerate(q):
        if count <= t:
            return i + 1
    return 4


def render(gh, tokens):
    now = datetime.datetime.now(datetime.timezone.utc)
    frm = now - datetime.timedelta(days=364)
    cal = gh_graphql(
        QUERY, {"login": LOGIN, "from": frm.isoformat(), "to": now.isoformat()}
    )["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = cal["weeks"][-53:]
    total = cal["totalContributions"]

    nz = sorted(
        d["contributionCount"] for w in weeks for d in w["contributionDays"]
        if d["contributionCount"] > 0
    )
    q = [nz[int(len(nz) * p)] for p in (0.25, 0.5, 0.75)] if nz else [1, 2, 3]

    hw, hh = 10, 5  # iso half-width / half-height
    x0, y0 = 230, 240

    cells = []
    for c, w in enumerate(weeks):
        for r, d in enumerate(w["contributionDays"]):
            cells.append((c + r, c, r, d["contributionCount"]))
    cells.sort()

    city = []
    for depth, c, r, count in cells:
        lvl = _level(count, q)
        X = x0 + (c - r) * hw
        Y = y0 + (c + r) * hh
        top, left, right = FACES[lvl]
        h = HEIGHTS[lvl]
        if lvl >= 2:
            h += (c * 31 + r * 17) % 9  # subtle skyline variation
        if lvl == 0:
            city.append(
                f'<polygon points="{X},{Y - hh} {X + hw},{Y} {X},{Y + hh} {X - hw},{Y}" '
                f'fill="{top}" stroke="#1a2330" stroke-width="0.4"/>'
            )
            continue
        yt = Y - h
        city.append(
            f'<polygon points="{X - hw},{yt} {X},{yt + hh} {X},{Y + hh} {X - hw},{Y}" fill="{left}"/>'
            f'<polygon points="{X},{yt + hh} {X + hw},{yt} {X + hw},{Y} {X},{Y + hh}" fill="{right}"/>'
            f'<polygon points="{X},{yt - hh} {X + hw},{yt} {X},{yt + hh} {X - hw},{yt}" fill="{top}"/>'
        )
        # building skin: window rows on both faces for mid+ towers
        if h >= 26:
            t = 6
            while t < h - 6:
                for f in (0.3, 0.68):
                    wy = yt + hh * f + t
                    lit = (c * 13 + r * 7 + t) % 5 < 2
                    city.append(
                        f'<rect x="{X - hw + f * hw - 1:.1f}" y="{wy:.1f}" width="2" height="3" '
                        f'fill="{WIN_LIT if lit else WIN_DARK}" opacity="{0.85 if lit else 0.6}"/>'
                    )
                    lit2 = (c * 7 + r * 11 + t) % 4 == 0
                    city.append(
                        f'<rect x="{X + f * hw - 1:.1f}" y="{yt + hh - f * hh + t:.1f}" width="2" height="3" '
                        f'fill="{WIN_LIT if lit2 else WIN_DARK}" opacity="{0.9 if lit2 else 0.5}"/>'
                    )
                t += 8

    stars = "".join(
        f'<circle cx="{(i * 97) % 900 + 20}" cy="{(i * 53) % 130 + 12}" r="0.8" '
        f'fill="#cdd9e5" opacity="{0.15 + (i % 3) * 0.12:.2f}"/>'
        for i in range(46)
    )

    legend = "".join(
        f'<rect x="{70 + i * 22}" y="{H - 30}" width="14" height="8" rx="2" fill="{FACES[i][0]}"/>'
        for i in range(5)
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{SKY_TOP}"/>
    <stop offset="0.32" stop-color="{SKY_MID}"/>
    <stop offset="0.42" stop-color="{HORIZON}"/>
    <stop offset="0.44" stop-color="#0a0f17"/>
    <stop offset="1" stop-color="#070b10"/>
  </linearGradient>
  <filter id="fog" x="-20%" y="-50%" width="140%" height="200%">
    <feGaussianBlur stdDeviation="14"/>
  </filter>
</defs>
<rect width="{W}" height="{H}" rx="14" fill="url(#sky)" stroke="{BORDER}"/>
{stars}
<circle cx="852" cy="52" r="14" fill="#e8eef5" opacity="0.85"/>
<circle cx="846" cy="47" r="13" fill="{SKY_TOP}"/>
{_skyline()}
<ellipse cx="320" cy="{HORIZON_Y + 4}" rx="320" ry="16" fill="#9fb2c8" opacity="0.05" filter="url(#fog)"/>
{"".join(city)}
<text x="24" y="34" font-size="13" font-weight="700" fill="{MINT_HI}" letter-spacing="2">SAN FRANCISCO · CONTRIBUTION DISTRICT</text>
<text x="24" y="54" font-size="10" fill="{MUTED}">53 WEEKS × 7 DAYS · EVERY BUILDING IS A DAY OF COMMITS</text>
<text x="{W - 24}" y="34" text-anchor="end" font-size="12" fill="{AMBER}" font-weight="700">{total:,} CONTRIBUTIONS</text>
<text x="{W - 24}" y="52" text-anchor="end" font-size="10" fill="{MUTED}">ROLLING 365 DAYS · {now:%Y-%m-%d}</text>
<text x="24" y="{H - 22}" font-size="9" fill="{MUTED}">LESS</text>
{legend}
<text x="{70 + 5 * 22 + 8}" y="{H - 22}" font-size="9" fill="{MUTED}">MORE</text>
</svg>"""
    write_svg("city.svg", svg)
