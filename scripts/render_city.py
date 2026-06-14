"""San Francisco contribution city.

A rolling year of GitHub contributions rendered as an isometric SF district:
every day is a lot, every commit builds it taller. Empty days are streets, so
the famous grid shows through. Low days are Victorian row houses (the Painted
Ladies), busy days grow into mid-rises with rooftop water tanks, and your peak
days rise into the city's landmarks — the Transamerica Pyramid, Salesforce
Tower, and Coit Tower. Lit warm by a dusk sun against cool bay shadow, seated on
a ground plane in front of the real skyline (assets/sf-bg.jpg).
"""
import base64
import datetime
import pathlib

from common import LOGIN, gh_graphql, write_svg

MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"
ROOT = pathlib.Path(__file__).resolve().parent.parent

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

# ---- dusk lighting -------------------------------------------------------
# Each building palette is (top, left, right): a warm sun-lit roof, a mid fill
# face, and a cool bay-shadow face. Warm-key / cool-fill is what reads as 3D.
BODY = {
    # SF pastels for the low-rise/row-house fabric, lit at dusk.
    "cream":   ("#f0dcc0", "#cf9f81", "#7d6a6f"),
    "rose":    ("#f1c9c4", "#cf938f", "#74616c"),
    "sage":    ("#cfdcc2", "#9aae8c", "#5f6566"),
    "sky":     ("#cfdbe6", "#93a7bd", "#5a6072"),
    "butter":  ("#f1dca6", "#cdac74", "#766a5c"),
    "terra":   ("#e8b79a", "#c08560", "#6e5a54"),
}
BODY_KEYS = list(BODY)
# Landmarks get their own materials.
PYRAMID = ("#eef0ea", "#cdd0cb", "#7e8487")   # Transamerica: white quartz
SALES   = ("#cfe0ec", "#94b3cb", "#586a82")   # Salesforce: blue glass
COIT    = ("#e9ddc2", "#c4b288", "#7a6f5f")   # Coit: pale concrete
ROOF    = ("#9c4a3c", "#7d3a30", "#552a25")   # terracotta shingle

WIN_LIT = "#ffd479"
WIN_DARK = "#11171f"
AMBER = "#ffb454"
WARM_HI = "#ffe1a8"
FG = "#cdd8e6"
MUTED = "#94a3b6"
BORDER = "#1c2430"
SHADOW = "#0a0e16"
GROUND_T = "#1b2330"   # ground plane top (asphalt dusk)
GROUND_L = "#141a25"
GROUND_R = "#0e131c"
STREET = "#222c3b"

# intensity -> nominal storeys (height grows with commits)
HEIGHTS = [0, 12, 22, 34, 50]

W, H = 940, 680
HW, HH = 12, 6          # iso half-width / half-height of a day-tile
X0, Y0 = 196, 150


def _level(count, q):
    if count <= 0:
        return 0
    for i, t in enumerate(q):
        if count <= t:
            return i + 1
    return 4


def _iso(c, r):
    return X0 + (c - r) * HW, Y0 + (c + r) * HH


def _prism(X, Y, h, pal, hw=HW, hh=HH, top_extra=""):
    """Three visible faces of a box of height h rising from tile (X, Y)."""
    top, left, right = pal
    yt = Y - h
    return (
        f'<polygon points="{X-hw},{yt} {X},{yt+hh} {X},{Y+hh} {X-hw},{Y}" fill="{left}"/>'
        f'<polygon points="{X},{yt+hh} {X+hw},{yt} {X+hw},{Y} {X},{Y+hh}" fill="{right}"/>'
        f'<polygon points="{X},{yt-hh} {X+hw},{yt} {X},{yt+hh} {X-hw},{yt}" fill="{top}"{top_extra}/>'
    ), yt


def _windows(X, Y, h, hw, cols, seed):
    """Lit/dark window grid on both visible side faces."""
    out = []
    t = 5
    band = 0
    while t < h - 4:
        for f in (0.32, 0.66):
            lit = (seed * 13 + band * 7 + int(f * 10)) % 5 < 2
            out.append(
                f'<rect x="{X-hw + f*hw - 0.9:.1f}" y="{Y - h + hh_(hw)*f + t:.1f}" '
                f'width="1.7" height="2.4" fill="{WIN_LIT if lit else WIN_DARK}" '
                f'opacity="{0.85 if lit else 0.5}"/>'
            )
            lit2 = (seed * 7 + band * 11 + int(f * 10)) % 4 == 0
            out.append(
                f'<rect x="{X + f*hw - 0.9:.1f}" y="{Y - h + hh_(hw) - hh_(hw)*f + t:.1f}" '
                f'width="1.7" height="2.4" fill="{WIN_LIT if lit2 else WIN_DARK}" '
                f'opacity="{0.9 if lit2 else 0.42}"/>'
            )
        t += 6
        band += 1
    return "".join(out)


def hh_(hw):
    # keep window slant proportional to tile foreshortening
    return HH * (hw / HW)


def _shadow(c, r, h):
    """Cast-shadow smear of a tile's footprint, offset toward lower-right."""
    X, Y = _iso(c, r)
    dx, dy = h * 0.55, h * 0.30
    return (
        f'<polygon points="{X},{Y-HH} {X+HW},{Y} {X+HW+dx:.0f},{Y+dy:.0f} '
        f'{X+dx:.0f},{Y+HH+dy:.0f} {X-HW+dx:.0f},{Y+dy:.0f} {X-HW},{Y}" '
        f'fill="{SHADOW}" opacity="0.20"/>'
    )


def _rowhouse(c, r, h, seed):
    """Low Victorian: short body + bay window + pitched shingle roof."""
    X, Y = _iso(c, r)
    pal = BODY[BODY_KEYS[seed % len(BODY_KEYS)]]
    body, yt = _prism(X, Y, h, pal)
    # pitched roof: two front slopes meeting a raised ridge
    apex = yt - 6
    roof = (
        f'<polygon points="{X-HW},{yt} {X},{yt+HH} {X},{apex}" fill="{ROOF[1]}"/>'
        f'<polygon points="{X},{yt+HH} {X+HW},{yt} {X},{apex}" fill="{ROOF[0]}"/>'
    )
    # bay window bump on the sunlit-ish front-right face
    bay = (
        f'<rect x="{X+2:.0f}" y="{Y-h+3:.0f}" width="4" height="{max(4,h-6):.0f}" '
        f'fill="{WIN_LIT}" opacity="0.5"/>'
    )
    return body + roof + bay


def _midrise(c, r, h, seed, water_tank):
    """Mid-rise: windowed body + parapet, sometimes a rooftop water tank."""
    X, Y = _iso(c, r)
    pal = BODY[BODY_KEYS[(seed + 2) % len(BODY_KEYS)]]
    body, yt = _prism(X, Y, h, pal)
    win = _windows(X, Y, h, HW, 2, seed)
    # parapet rim
    rim = (
        f'<polygon points="{X},{yt-HH-2} {X+HW},{yt-2} {X},{yt+HH-2} {X-HW},{yt-2}" '
        f'fill="none" stroke="{WARM_HI}" stroke-width="0.5" opacity="0.5"/>'
    )
    tank = ""
    if water_tank:
        tx, ty = X, yt - 3
        tank = (
            f'<rect x="{tx-2.5}" y="{ty-7}" width="5" height="7" fill="{ROOF[1]}"/>'
            f'<ellipse cx="{tx}" cy="{ty-7}" rx="2.5" ry="1.1" fill="{ROOF[0]}"/>'
            f'<line x1="{tx-2}" y1="{ty}" x2="{tx-2}" y2="{ty+2}" stroke="{ROOF[2]}" stroke-width="0.6"/>'
            f'<line x1="{tx+2}" y1="{ty}" x2="{tx+2}" y2="{ty+2}" stroke="{ROOF[2]}" stroke-width="0.6"/>'
        )
    return body + win + rim + tank


def _pyramid(c, r):
    """Transamerica Pyramid: tapering white spire."""
    X, Y = _iso(c, r)
    bw, bh = HW - 1, HH - 1
    apex = Y - 90
    return (
        f'<polygon points="{X-bw},{Y} {X},{Y+bh} {X},{apex}" fill="{PYRAMID[1]}"/>'
        f'<polygon points="{X},{Y+bh} {X+bw},{Y} {X},{apex}" fill="{PYRAMID[0]}"/>'
        # sunlit front edge highlight
        f'<line x1="{X}" y1="{Y+bh}" x2="{X}" y2="{apex}" stroke="{WARM_HI}" '
        f'stroke-width="0.7" opacity="0.6"/>'
        f'<line x1="{X}" y1="{apex}" x2="{X}" y2="{apex-13}" stroke="{PYRAMID[0]}" stroke-width="1.4"/>'
        f'<circle cx="{X}" cy="{apex-13}" r="1.2" fill="{AMBER}" class="beacon"/>'
    )


def _salesforce(c, r):
    """Salesforce Tower: tall tapered tower with a lit rounded crown."""
    X, Y = _iso(c, r)
    h = 104
    body, yt = _prism(X, Y, h, SALES, hw=HW - 3, hh=HH - 1)
    win = _windows(X, Y, h, HW - 3, 2, c + r + 5)
    crown = (
        f'<ellipse cx="{X}" cy="{yt-2}" rx="{HW-4}" ry="3" fill="{SALES[0]}"/>'
        f'<ellipse cx="{X}" cy="{yt-8}" rx="{HW-6}" ry="7" fill="{SALES[0]}" opacity="0.92"/>'
        f'<ellipse cx="{X}" cy="{yt-11}" rx="4" ry="4" fill="{WARM_HI}" opacity="0.95" class="beacon"/>'
        f'<ellipse cx="{X}" cy="{yt-11}" rx="7" ry="7" fill="{WARM_HI}" opacity="0.18" class="beacon"/>'
    )
    return body + win + crown


def _coit(c, r):
    """Coit Tower: pale fluted column with an arched crown."""
    X, Y = _iso(c, r)
    h = 58
    body, yt = _prism(X, Y, h, COIT, hw=HW - 4, hh=HH - 1)
    flutes = "".join(
        f'<line x1="{X-HW+5+i*2.2:.1f}" y1="{Y-h+8:.1f}" x2="{X-HW+5+i*2.2:.1f}" y2="{Y:.1f}" '
        f'stroke="{COIT[2]}" stroke-width="0.4" opacity="0.5"/>'
        for i in range(6)
    )
    crown = (
        f'<rect x="{X-HW+4}" y="{yt-4}" width="{2*(HW-4)}" height="5" fill="{COIT[1]}"/>'
        f'<ellipse cx="{X}" cy="{yt-4}" rx="{HW-4}" ry="2" fill="{COIT[0]}"/>'
    )
    return body + flutes + crown


def _street(c, r, paint):
    X, Y = _iso(c, r)
    s = (
        f'<polygon points="{X},{Y-HH} {X+HW},{Y} {X},{Y+HH} {X-HW},{Y}" '
        f'fill="{STREET}"/>'
    )
    if paint:
        s += (
            f'<line x1="{X-HW*0.5:.0f}" y1="{Y-HH*0.5:.0f}" x2="{X+HW*0.5:.0f}" '
            f'y2="{Y+HH*0.5:.0f}" stroke="{AMBER}" stroke-width="0.5" '
            f'stroke-dasharray="1.5 1.5" opacity="0.35"/>'
        )
    return s


def render(gh, tokens):
    now = datetime.datetime.now(datetime.timezone.utc)
    frm = now - datetime.timedelta(days=364)
    cal = gh_graphql(
        QUERY, {"login": LOGIN, "from": frm.isoformat(), "to": now.isoformat()}
    )["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = cal["weeks"][-53:]
    total = cal["totalContributions"]

    days_flat = [d for w in weeks for d in w["contributionDays"]]
    counts = [d["contributionCount"] for d in days_flat]
    nz = sorted(c for c in counts if c > 0)
    q = [nz[int(len(nz) * p)] for p in (0.25, 0.5, 0.75)] if nz else [1, 2, 3]

    streak = 0
    for c in reversed(counts):
        if c > 0:
            streak += 1
        else:
            break
    active = sum(1 for c in counts if c > 0)
    peak_day = max(days_flat, key=lambda d: d["contributionCount"])

    bg64 = base64.b64encode((ROOT / "assets" / "sf-bg.jpg").read_bytes()).decode()

    # Build per-cell records, depth-sorted back -> front.
    cells = []
    for c, w in enumerate(weeks):
        for r, d in enumerate(w["contributionDays"]):
            cells.append((c, r, d))
    cells.sort(key=lambda t: (t[0] + t[1], t[0]))

    # Assign landmarks to the top peak days so the icons actually show.
    lvl4 = sorted(
        (d["contributionCount"], c, r, d) for c, r, d in cells
        if _level(d["contributionCount"], q) == 4
    )
    landmarks = {}
    icons = [_pyramid, _salesforce, _coit]
    for i, (_, c, r, _d) in enumerate(reversed(lvl4)):
        if i < 5:                       # a few icons, not a pincushion
            landmarks[(c, r)] = icons[i % 3]

    shadows, ground, city = [], [], []
    peak_pos = None
    for c, r, d in cells:
        count = d["contributionCount"]
        lvl = _level(count, q)
        X, Y = _iso(c, r)
        seed = c * 31 + r * 17

        if lvl == 0:
            ground.append(_street(c, r, paint=(c + r) % 9 == 0))
            continue

        h = HEIGHTS[lvl] + (seed % 7 if lvl >= 2 else seed % 3)
        shadows.append(_shadow(c, r, h if (c, r) not in landmarks else 70))

        if (c, r) in landmarks:
            city.append(landmarks[(c, r)](c, r))
            top_y = Y - (96 if landmarks[(c, r)] is _pyramid else 104 if landmarks[(c, r)] is _salesforce else 58)
        elif lvl == 1:
            city.append(_rowhouse(c, r, h, seed))
            top_y = Y - h - 6
        else:
            city.append(_midrise(c, r, h, seed, water_tank=lvl >= 3 and seed % 3 == 0))
            top_y = Y - h

        if d["date"] == peak_day["date"]:
            peak_pos = (X, top_y, count, d["date"])

    # ground slab under the whole grid (so the city is seated, not floating)
    gx0, gy0 = _iso(0, 6)
    gx1, gy1 = _iso(52, 6)
    gx2, gy2 = _iso(52, 0)
    gx_top, gy_top = _iso(0, 0)
    slab = (
        f'<polygon points="{gx_top},{gy_top-HH} {_iso(52,0)[0]},{_iso(52,0)[1]-HH} '
        f'{_iso(52,6)[0]},{_iso(52,6)[1]+HH} {_iso(0,6)[0]},{_iso(0,6)[1]+HH}" '
        f'fill="{GROUND_T}" stroke="{GROUND_L}" stroke-width="1"/>'
    )

    # peak-day pennant
    pennant = ""
    if peak_pos:
        px, py, pc, pdate = peak_pos
        py = max(py, 72)
        label = f"PEAK {pc} · {datetime.date.fromisoformat(pdate):%b %d}".upper()
        lw = len(label) * 5.6 + 14
        pennant = (
            f'<line x1="{px}" y1="{py}" x2="{px}" y2="{py-26}" stroke="{AMBER}" stroke-width="1"/>'
            f'<polygon points="{px},{py-26} {px+15},{py-22} {px},{py-18}" fill="{AMBER}"/>'
            f'<rect x="{px-lw/2}" y="{py-45}" width="{lw}" height="15" rx="3" '
            f'fill="#070b10" fill-opacity="0.82" stroke="{AMBER}" stroke-width="0.6"/>'
            f'<text x="{px}" y="{py-34}" text-anchor="middle" font-size="9" '
            f'fill="{AMBER}" font-weight="700">{label}</text>'
        )

    # axes: months along the front-right edge, weekdays down the left
    axes = []
    seen = None
    for c, w in enumerate(weeks):
        d0 = datetime.date.fromisoformat(w["contributionDays"][0]["date"])
        if d0.month != seen:
            seen = d0.month
            if c > 0:
                X, Y = _iso(c, 6)
                mon = f"{d0:%b}".upper()
                axes.append(
                    f'<text x="{X+4}" y="{Y+HH+13}" font-size="8" fill="{FG}" '
                    f'opacity="0.85" transform="rotate(26 {X+4} {Y+HH+13})">{mon}</text>'
                )

    legend_y = H - 78
    swatches = "".join(
        f'<rect x="{40+i*16}" y="{legend_y}" width="12" height="10" rx="1.5" '
        f'fill="{(GROUND_T, BODY["cream"][0], BODY["sky"][0], BODY["terra"][0], PYRAMID[0])[i]}" '
        f'stroke="#0a0e16" stroke-width="0.6"/>'
        for i in range(5)
    )

    created = datetime.datetime.fromisoformat(
        gh["user"]["created_at"].replace("Z", "+00:00")
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <clipPath id="card"><rect width="{W}" height="{H}" rx="14"/></clipPath>
  <linearGradient id="dusk" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#1a2740" stop-opacity="0"/>
    <stop offset="1" stop-color="#0a0e16" stop-opacity="0.55"/>
  </linearGradient>
  <filter id="soft" x="-30%" y="-30%" width="160%" height="160%">
    <feGaussianBlur stdDeviation="1.4"/>
  </filter>
  <style>
    @keyframes beacon {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.2; }} }}
    .beacon {{ animation: beacon 2.6s ease-in-out infinite; }}
  </style>
</defs>
<g clip-path="url(#card)">
  <image href="data:image/jpeg;base64,{bg64}" x="0" y="0" width="{W}" height="{H}" preserveAspectRatio="xMidYMax slice"/>
  <rect width="{W}" height="{H}" fill="url(#dusk)"/>
  {slab}
  <g filter="url(#soft)">{"".join(shadows)}</g>
  {"".join(ground)}
  {"".join(city)}
  {pennant}
</g>
{"".join(axes)}
<text x="26" y="36" font-size="14" font-weight="700" fill="{WARM_HI}" letter-spacing="2">SAN FRANCISCO · CONTRIBUTION DISTRICT</text>
<text x="26" y="56" font-size="10" fill="{FG}">EVERY DAY A LOT · ROW HOUSES TO LANDMARKS AS COMMITS RISE · ROLLING 365D</text>
<text x="{W-26}" y="36" text-anchor="end" font-size="13" fill="{AMBER}" font-weight="700">{total:,} CONTRIBUTIONS</text>
<text x="{W-26}" y="56" text-anchor="end" font-size="10" fill="{FG}">ACTIVE {active}/365 · STREAK {streak}D · PEAK {peak_day['contributionCount']}</text>
<text x="40" y="{legend_y-6}" font-size="8" fill="{MUTED}">QUIET</text>
{swatches}
<text x="{40+5*16+6}" y="{legend_y+8}" font-size="8" fill="{MUTED}">BUSY · EST. {created.year}</text>
<rect width="{W}" height="{H}" rx="14" fill="none" stroke="{BORDER}"/>
</svg>"""
    write_svg("city.svg", svg)
