"""San Francisco contribution city.

A rolling year of GitHub contributions as an isometric SF skyline: empty days
are streets, quiet days are Victorian row houses, and as commits rise the lots
grow into tapered, glass-faced high-rises with setbacks and spires. Peak days
become the city's landmarks — the Transamerica Pyramid, Salesforce Tower and
Coit Tower. Lit by a warm dusk sun against cool bay shadow, seated on a ground
plane in front of the real skyline (assets/sf-bg.jpg).
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
# (top, left, right): warm sun-lit roof, mid fill face, cool bay-shadow face.
GLASS = {
    "steel":  ("#cfd8e6", "#8ea2bd", "#46506a"),
    "teal":   ("#bfe0dd", "#7fb0ac", "#3f5d62"),
    "amberg": ("#f0d8a8", "#c39f6b", "#6b5a4c"),
    "rose":   ("#eccbd2", "#bd8d97", "#5f4f60"),
    "indigo": ("#c4cbe8", "#8388b8", "#454868"),
}
GLASS_KEYS = list(GLASS)
BODY = {
    "cream":  ("#f0dcc0", "#cf9f81", "#7d6a6f"),
    "rose":   ("#f1c9c4", "#cf938f", "#74616c"),
    "sage":   ("#cfdcc2", "#9aae8c", "#5f6566"),
    "sky":    ("#cfdbe6", "#93a7bd", "#5a6072"),
    "butter": ("#f1dca6", "#cdac74", "#766a5c"),
    "terra":  ("#e8b79a", "#c08560", "#6e5a54"),
}
BODY_KEYS = list(BODY)
PYRAMID = ("#eef0ea", "#cdd0cb", "#7e8487")
SALES   = ("#cfe0ec", "#94b3cb", "#586a82")
COIT    = ("#e9ddc2", "#c4b288", "#7a6f5f")
ROOF    = ("#9c4a3c", "#7d3a30", "#552a25")

WIN_LIT = "#ffd884"
AMBER = "#ffb454"
WARM_HI = "#ffe6b0"
FG = "#cdd8e6"
MUTED = "#94a3b6"
BORDER = "#1c2430"
SHADOW = "#080b12"
HAZE = "#243149"           # dusk atmosphere the far city fades into
GROUND_T = "#1b2330"
GROUND_L = "#141a25"
STREET = "#222c3b"

# intensity -> nominal height; real skyline range, not stubby cubes
HEIGHTS = [0, 26, 58, 104, 168]

W, H = 940, 720
HW, HH = 13, 6.5         # iso half-width / half-height of a day-tile
X0, Y0 = 210, 196


def _level(count, q):
    if count <= 0:
        return 0
    for i, t in enumerate(q):
        if count <= t:
            return i + 1
    return 4


def _iso(c, r):
    return X0 + (c - r) * HW, Y0 + (c + r) * HH


def _mix(a, b, t):
    a = a.lstrip("#"); b = b.lstrip("#")
    return "#" + "".join(
        f"{round(int(a[i:i+2],16)*(1-t) + int(b[i:i+2],16)*t):02x}"
        for i in (0, 2, 4)
    )


def _lerp(p, q, f):
    return (p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f)


def _hz(pal, depth):
    """Aerial perspective: fade far (low-depth) buildings toward dusk haze."""
    t = max(0.0, 0.34 - depth * 0.006)
    return tuple(_mix(c, HAZE, t) for c in pal)


def _facegrid(A, B, Ap, Bp, floors, seed, lit):
    """Floor lines + scattered lit windows across a tapered face A-B (bottom)
    to Ap-Bp (top)."""
    out = []
    for i in range(1, floors):
        f = i / floors
        p1, p2 = _lerp(A, Ap, f), _lerp(B, Bp, f)
        out.append(
            f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" '
            f'stroke="#0b0f17" stroke-width="0.4" opacity="0.35"/>'
        )
        for k in range(1, 5):
            if (seed * 17 + i * 7 + k * 5) % 6 < (3 if lit else 1):
                g = k / 5
                w = _lerp(p1, p2, g)
                out.append(
                    f'<rect x="{w[0]-0.7:.1f}" y="{w[1]-1.0:.1f}" width="1.4" height="1.8" '
                    f'fill="{WIN_LIT}" opacity="0.85"/>'
                )
    return "".join(out)


def _seg(X, yb, h, bw, tw, pal, seed, lit, depth=30):
    """One tapered frustum segment; returns (svg, top_center_y, top_hw)."""
    top, left, right = _hz(pal, depth)
    bhh, thh = bw * HH / HW, tw * HH / HW
    yt = yb - h
    # corners: L/F/R bottom, primed = top
    L, F, R = (X - bw, yb), (X, yb + bhh), (X + bw, yb)
    Lp, Fp, Rp = (X - tw, yt), (X, yt + thh), (X + tw, yt)
    Bp = (X, yt - thh)
    svg = (
        f'<polygon points="{L[0]:.1f},{L[1]:.1f} {F[0]:.1f},{F[1]:.1f} {Fp[0]:.1f},{Fp[1]:.1f} {Lp[0]:.1f},{Lp[1]:.1f}" fill="{left}"/>'
        f'<polygon points="{F[0]:.1f},{F[1]:.1f} {R[0]:.1f},{R[1]:.1f} {Rp[0]:.1f},{Rp[1]:.1f} {Fp[0]:.1f},{Fp[1]:.1f}" fill="{right}"/>'
        f'<polygon points="{Lp[0]:.1f},{Lp[1]:.1f} {Fp[0]:.1f},{Fp[1]:.1f} {Rp[0]:.1f},{Rp[1]:.1f} {Bp[0]:.1f},{Bp[1]:.1f}" fill="{top}"/>'
        # glass sheen on the lit left face
        f'<polygon points="{L[0]:.1f},{L[1]:.1f} {F[0]:.1f},{F[1]:.1f} {Fp[0]:.1f},{Fp[1]:.1f} {Lp[0]:.1f},{Lp[1]:.1f}" fill="url(#sheen)" opacity="0.5"/>'
    )
    floors = max(2, int(h / 7))
    svg += _facegrid(L, F, Lp, Fp, floors, seed, lit)
    svg += _facegrid(F, R, Fp, Rp, floors, seed + 3, lit)
    return svg, yt, tw


def _tower(c, r, h, seed, glassy):
    """Tapered high-rise, with a setback for tall ones + a rooftop crown."""
    X, Y = _iso(c, r)
    pal = (GLASS if glassy else BODY)[(GLASS_KEYS if glassy else BODY_KEYS)[seed % 5]]
    bw = HW - 2
    dep = c + r
    out = []
    if h > 90:                       # stepped setback tower
        h1 = h * 0.62
        s1, yt1, tw1 = _seg(X, Y, h1, bw, bw * 0.82, pal, seed, glassy, dep)
        s2, yt2, tw2 = _seg(X, yt1, h - h1, bw * 0.78, bw * 0.5, pal, seed + 1, glassy, dep)
        out += [s1, s2]
        topx, topy, topw = X, yt2, tw2
    else:
        s1, yt1, tw1 = _seg(X, Y, h, bw, bw * 0.7, pal, seed, glassy, dep)
        out.append(s1)
        topx, topy, topw = X, yt1, tw1
    # rooftop crown: parapet box + antenna for the tallest
    out.append(
        f'<polygon points="{topx},{topy-topw*HH/HW-2} {topx+topw},{topy-2} '
        f'{topx},{topy+topw*HH/HW-2} {topx-topw},{topy-2}" fill="{WARM_HI}" opacity="0.35"/>'
    )
    if h > 120:
        out.append(
            f'<line x1="{topx}" y1="{topy}" x2="{topx}" y2="{topy-16}" stroke="{MUTED}" stroke-width="1"/>'
            f'<circle cx="{topx}" cy="{topy-16}" r="1.2" fill="{AMBER}" class="beacon"/>'
        )
    return "".join(out), topy


def _rowhouse(c, r, h, seed):
    X, Y = _iso(c, r)
    pal = BODY[BODY_KEYS[seed % len(BODY_KEYS)]]
    bw = HW - 1
    body, yt, tw = _seg(X, Y, h, bw, bw * 0.96, pal, seed, False, c + r)
    apex = yt - 9
    roof = (
        f'<polygon points="{X-bw},{yt} {X},{yt+bw*HH/HW} {X},{apex}" fill="{ROOF[1]}"/>'
        f'<polygon points="{X},{yt+bw*HH/HW} {X+bw},{yt} {X},{apex}" fill="{ROOF[0]}"/>'
    )
    return body + roof, apex


def _pyramid(c, r):
    X, Y = _iso(c, r)
    bw, bh = HW - 1, (HW - 1) * HH / HW
    apex = Y - 150
    return (
        f'<polygon points="{X-bw},{Y} {X},{Y+bh} {X},{apex}" fill="{PYRAMID[1]}"/>'
        f'<polygon points="{X},{Y+bh} {X+bw},{Y} {X},{apex}" fill="{PYRAMID[0]}"/>'
        f'<line x1="{X}" y1="{Y+bh}" x2="{X}" y2="{apex}" stroke="{WARM_HI}" stroke-width="0.8" opacity="0.65"/>'
        f'<line x1="{X}" y1="{apex}" x2="{X}" y2="{apex-18}" stroke="{PYRAMID[0]}" stroke-width="1.5"/>'
        f'<circle cx="{X}" cy="{apex-18}" r="1.3" fill="{AMBER}" class="beacon"/>'
    ), apex - 18


def _salesforce(c, r):
    X, Y = _iso(c, r)
    h = 196
    body, yt, tw = _seg(X, Y, h, HW - 3, (HW - 3) * 0.42, SALES, c + r + 5, True, c + r)
    crown = (
        f'<ellipse cx="{X}" cy="{yt-2}" rx="{tw+1}" ry="3" fill="{SALES[0]}"/>'
        f'<ellipse cx="{X}" cy="{yt-9}" rx="{tw-1}" ry="9" fill="{SALES[0]}" opacity="0.92"/>'
        f'<ellipse cx="{X}" cy="{yt-13}" rx="4" ry="5" fill="{WARM_HI}" opacity="0.95" class="beacon"/>'
        f'<ellipse cx="{X}" cy="{yt-13}" rx="8" ry="9" fill="{WARM_HI}" opacity="0.16" class="beacon"/>'
    )
    return body + crown, yt - 13


def _coit(c, r):
    X, Y = _iso(c, r)
    h = 92
    body, yt, tw = _seg(X, Y, h, HW - 4, (HW - 4) * 0.9, COIT, c + r, False, c + r)
    crown = (
        f'<rect x="{X-tw}" y="{yt-5}" width="{2*tw}" height="6" fill="{COIT[1]}"/>'
        f'<ellipse cx="{X}" cy="{yt-5}" rx="{tw}" ry="2" fill="{COIT[0]}"/>'
    )
    return body + crown, yt - 5


def _street(c, r, paint):
    X, Y = _iso(c, r)
    s = (
        f'<polygon points="{X},{Y-HH} {X+HW},{Y} {X},{Y+HH} {X-HW},{Y}" fill="{STREET}"/>'
    )
    if paint:
        s += (
            f'<line x1="{X-HW*0.5:.0f}" y1="{Y-HH*0.5:.0f}" x2="{X+HW*0.5:.0f}" '
            f'y2="{Y+HH*0.5:.0f}" stroke="{AMBER}" stroke-width="0.5" '
            f'stroke-dasharray="1.5 1.5" opacity="0.32"/>'
        )
    return s


def _shadow(c, r, h):
    X, Y = _iso(c, r)
    dx, dy = h * 0.5, h * 0.27
    return (
        f'<polygon points="{X},{Y-HH} {X+HW},{Y} {X+HW+dx:.0f},{Y+dy:.0f} '
        f'{X+dx:.0f},{Y+HH+dy:.0f} {X-HW+dx:.0f},{Y+dy:.0f} {X-HW},{Y}" '
        f'fill="{SHADOW}" opacity="0.22"/>'
    )


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

    cells = []
    for c, w in enumerate(weeks):
        for r, d in enumerate(w["contributionDays"]):
            cells.append((c, r, d))
    cells.sort(key=lambda t: (t[0] + t[1], t[0]))

    lvl4 = sorted(
        (d["contributionCount"], c, r) for c, r, d in cells
        if _level(d["contributionCount"], q) == 4
    )
    landmarks, icons = {}, [_pyramid, _salesforce, _coit]
    for i, (_, c, r) in enumerate(reversed(lvl4)):
        if i < 5:
            landmarks[(c, r)] = icons[i % 3]

    shadows, ground, city = [], [], []
    peak_pos = None
    for c, r, d in cells:
        count = d["contributionCount"]
        lvl = _level(count, q)
        X, Y = _iso(c, r)
        seed = c * 31 + r * 17
        depth = c + r

        if lvl == 0:
            ground.append(_street(c, r, paint=depth % 9 == 0))
            continue

        h = HEIGHTS[lvl] + (seed % 14 if lvl >= 2 else seed % 5)
        shadows.append(_shadow(c, r, h if (c, r) not in landmarks else 150))

        if (c, r) in landmarks:
            svg, top_y = landmarks[(c, r)](c, r)
        elif lvl == 1:
            svg, top_y = _rowhouse(c, r, h, seed)
        else:
            svg, top_y = _tower(c, r, h, seed, glassy=lvl >= 3)
        city.append(svg)

        if d["date"] == peak_day["date"]:
            peak_pos = (X, top_y, count, d["date"])

    slab = (
        f'<polygon points="{_iso(0,0)[0]},{_iso(0,0)[1]-HH} {_iso(52,0)[0]},{_iso(52,0)[1]-HH} '
        f'{_iso(52,6)[0]},{_iso(52,6)[1]+HH} {_iso(0,6)[0]},{_iso(0,6)[1]+HH}" '
        f'fill="{GROUND_T}" stroke="{GROUND_L}" stroke-width="1"/>'
    )

    pennant = ""
    if peak_pos:
        px, py, pc, pdate = peak_pos
        py = max(py, 78)
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

    legend_y = H - 70
    swatches = "".join(
        f'<rect x="{40+i*16}" y="{legend_y}" width="12" height="10" rx="1.5" '
        f'fill="{(STREET, BODY["cream"][0], BODY["sky"][0], GLASS["steel"][0], PYRAMID[0])[i]}" '
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
    <stop offset="1" stop-color="#0a0e16" stop-opacity="0.5"/>
  </linearGradient>
  <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#ffffff" stop-opacity="0.32"/>
    <stop offset="0.5" stop-color="#ffffff" stop-opacity="0.04"/>
    <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
  </linearGradient>
  <filter id="soft" x="-30%" y="-30%" width="160%" height="160%">
    <feGaussianBlur stdDeviation="1.6"/>
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
<text x="26" y="56" font-size="10" fill="{FG}">EVERY DAY A LOT · ROW HOUSES TO HIGH-RISES AS COMMITS RISE · ROLLING 365D</text>
<text x="{W-26}" y="36" text-anchor="end" font-size="13" fill="{AMBER}" font-weight="700">{total:,} CONTRIBUTIONS</text>
<text x="{W-26}" y="56" text-anchor="end" font-size="10" fill="{FG}">ACTIVE {active}/365 · STREAK {streak}D · PEAK {peak_day['contributionCount']}</text>
<text x="40" y="{legend_y-6}" font-size="8" fill="{MUTED}">QUIET</text>
{swatches}
<text x="{40+5*16+6}" y="{legend_y+8}" font-size="8" fill="{MUTED}">BUSY · EST. {created.year}</text>
<rect width="{W}" height="{H}" rx="14" fill="none" stroke="{BORDER}"/>
</svg>"""
    write_svg("city.svg", svg)
