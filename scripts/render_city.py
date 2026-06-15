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
PYRAMID = ("#eef0ea", "#cdd0cb", "#7e8487")   # Transamerica: white quartz
SALES   = ("#cfe0ec", "#94b3cb", "#586a82")   # Salesforce: blue glass
COIT    = ("#e9ddc2", "#c4b288", "#7a6f5f")   # Coit: bare concrete
BOFA    = ("#6a4450", "#4c2c34", "#2c181d")   # 555 California: red granite
FREMONT = ("#cdd9e4", "#93a7bd", "#586679")   # 181 Fremont: cool glass
FERRY   = ("#ece3cf", "#cfc2a4", "#8f8366")   # Ferry Building: Beaux-Arts stone
STONE   = ("#e9e1cf", "#cdc3a8", "#8d8268")   # City Hall: granite
GOLD    = ("#f2d06a", "#cf9f34", "#8a6a22")   # City Hall: gilded dome
SUTRO_O = "#e4572e"        # Sutro Tower international orange
SUTRO_W = "#f1efe8"        # Sutro Tower white
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
    """Painted-Lady Victorian: steep gable, projecting bay window, white trim,
    a pastel palette per house."""
    X, Y = _iso(c, r)
    pal = BODY[BODY_KEYS[seed % len(BODY_KEYS)]]
    bw = HW - 1
    cn = _corners(X, Y, h, bw, bw)
    yt = cn["yt"]
    out = [_faces(cn, pal, c + r)]
    bhh = bw * HH / HW
    # white trim line under the eaves
    out.append(
        f'<line x1="{X-bw}" y1="{yt}" x2="{X}" y2="{yt+bhh:.1f}" stroke="{PYRAMID[0]}" stroke-width="0.8" opacity="0.7"/>'
        f'<line x1="{X}" y1="{yt+bhh:.1f}" x2="{X+bw}" y2="{yt}" stroke="{PYRAMID[0]}" stroke-width="0.8" opacity="0.7"/>'
    )
    # projecting bay window on the lit front-left face
    bx = _lerp(cn["L"], cn["F"], 0.5)
    out.append(
        f'<rect x="{bx[0]-2:.1f}" y="{bx[1]-h*0.55:.1f}" width="4" height="{h*0.45:.1f}" '
        f'rx="0.8" fill="{WIN_LIT}" opacity="0.55"/>'
    )
    # steep Queen-Anne gable
    apex = yt - 14
    top, left, right = ROOF
    out.append(
        _poly([(X - bw, yt), (X, yt + bhh), (X, apex)], left)
        + _poly([(X, yt + bhh), (X + bw, yt), (X, apex)], top)
        + f'<line x1="{X}" y1="{yt+bhh:.1f}" x2="{X}" y2="{apex}" stroke="{WARM_HI}" stroke-width="0.5" opacity="0.5"/>'
    )
    return "".join(out), apex


def _corners(X, yb, h, bw, tw):
    bhh, thh, yt = bw * HH / HW, tw * HH / HW, yb - h
    return {
        "L": (X - bw, yb), "F": (X, yb + bhh), "R": (X + bw, yb),
        "Lp": (X - tw, yt), "Fp": (X, yt + thh), "Rp": (X + tw, yt),
        "Bp": (X, yt - thh), "yt": yt,
    }


def _poly(pts, fill, extra=""):
    p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return f'<polygon points="{p}" fill="{fill}" {extra}/>'


def _faces(cn, pal, depth, sheen=True):
    top, left, right = _hz(pal, depth)
    s = (
        _poly([cn["L"], cn["F"], cn["Fp"], cn["Lp"]], left)
        + _poly([cn["F"], cn["R"], cn["Rp"], cn["Fp"]], right)
        + _poly([cn["Lp"], cn["Fp"], cn["Rp"], cn["Bp"]], top)
    )
    if sheen:
        s += _poly([cn["L"], cn["F"], cn["Fp"], cn["Lp"]], "url(#sheen)", 'opacity="0.5"')
    return s


# --- the famous ten -------------------------------------------------------

def _salesforce(c, r):
    """#1 Salesforce Tower: obelisk, rounded glass corners tapering inward,
    transparent latticework crown that dissolves into the sky."""
    X, Y = _iso(c, r)
    h = 212
    cn = _corners(X, Y, h, HW - 2, (HW - 2) * 0.56)
    out = [_faces(cn, SALES, c + r)]
    out.append(_facegrid(cn["L"], cn["F"], cn["Lp"], cn["Fp"], int(h / 8), c + r, True))
    out.append(_facegrid(cn["F"], cn["R"], cn["Fp"], cn["Rp"], int(h / 8), c + r + 3, True))
    yt, tw = cn["yt"], (HW - 2) * 0.56
    # lattice crown: thin verticals fanning past the top floor, fading up
    for k in range(-2, 3):
        x = X + k * tw / 2.4
        out.append(
            f'<line x1="{x:.1f}" y1="{yt:.1f}" x2="{X:.1f}" y2="{yt-24:.1f}" '
            f'stroke="{PYRAMID[0]}" stroke-width="0.7" opacity="0.5"/>'
        )
    out.append(
        f'<circle cx="{X}" cy="{yt-22}" r="2.6" fill="{WARM_HI}" class="beacon"/>'
        f'<circle cx="{X}" cy="{yt-22}" r="6" fill="{WARM_HI}" opacity="0.18" class="beacon"/>'
    )
    return "".join(out), yt - 24


def _transamerica(c, r):
    """#2 Transamerica Pyramid: 4-sided white pyramid, two flank wings for the
    elevator/stair shafts, capped by a tall aluminum spire."""
    X, Y = _iso(c, r)
    bw, bh = HW - 1, (HW - 1) * HH / HW
    apex = Y - 178
    top, left, right = PYRAMID
    out = [
        _poly([(X - bw, Y), (X, Y + bh), (X, apex)], left),
        _poly([(X, Y + bh), (X + bw, Y), (X, apex)], right),
        f'<line x1="{X}" y1="{Y+bh}" x2="{X}" y2="{apex}" stroke="{WARM_HI}" stroke-width="0.7" opacity="0.6"/>',
    ]
    # the two wings: vertical fins that flank the spire on the upper shaft and
    # stand proud of the narrowing pyramid (its distinctive shoulders)
    yb_w, yt_w = Y - 178 * 0.40, Y - 178 * 0.92
    fin = PYRAMID[2]
    out.append(_poly([(X - 5.5, yb_w), (X - 2.6, yb_w), (X - 1.4, yt_w), (X - 3.2, yt_w)], fin))
    out.append(_poly([(X + 2.6, yb_w), (X + 5.5, yb_w), (X + 3.2, yt_w), (X + 1.4, yt_w)], fin))
    out.append(f'<line x1="{X-3.9:.1f}" y1="{yb_w:.1f}" x2="{X-2.3:.1f}" y2="{yt_w:.1f}" stroke="{left}" stroke-width="0.5" opacity="0.6"/>')
    out.append(
        f'<line x1="{X}" y1="{apex}" x2="{X}" y2="{apex-26}" stroke="{MUTED}" stroke-width="1.4"/>'
        f'<circle cx="{X}" cy="{apex-26}" r="1.4" fill="{AMBER}" class="beacon"/>'
    )
    return "".join(out), apex - 26


def _sutro(c, r):
    """#3 Sutro Tower: orange-and-white three-legged lattice antenna that
    splits into a trident of prongs."""
    X, Y = _iso(c, r)
    sp = HW - 3                      # leg spread
    plat = Y - 118                   # platform where legs meet
    top = Y - 196                    # prong tips
    O, Wt = SUTRO_O, SUTRO_W
    out = []
    # three splayed legs (two front + center) meeting at the platform
    for lx in (X - sp, X, X + sp):
        out.append(
            f'<line x1="{lx:.1f}" y1="{Y:.1f}" x2="{X:.1f}" y2="{plat:.1f}" '
            f'stroke="{O}" stroke-width="2.2"/>'
        )
    # lattice cross-bracing on the legs (white)
    for f in (0.25, 0.5, 0.75):
        y = Y + (plat - Y) * f
        x1 = X + (X - sp - X) * (1 - f)
        x2 = X + (X + sp - X) * (1 - f)
        out.append(
            f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" '
            f'stroke="{Wt}" stroke-width="0.8" opacity="0.85"/>'
        )
    out.append(f'<rect x="{X-sp*0.7:.1f}" y="{plat-2:.1f}" width="{sp*1.4:.1f}" height="3" fill="{O}"/>')
    # trident: three prongs rising from the platform
    for px in (X - 5, X, X + 5):
        out.append(
            f'<line x1="{px:.1f}" y1="{plat:.1f}" x2="{px:.1f}" y2="{top:.1f}" '
            f'stroke="{O}" stroke-width="1.8"/>'
        )
        for yy in range(int(top), int(plat), 7):
            out.append(f'<line x1="{px-1.5:.1f}" y1="{yy}" x2="{px+1.5:.1f}" y2="{yy+3}" stroke="{Wt}" stroke-width="0.5" opacity="0.8"/>')
    out.append(f'<circle cx="{X}" cy="{top}" r="1.3" fill="{AMBER}" class="beacon"/>')
    return "".join(out), top


def _fremont(c, r):
    """#4 181 Fremont: tapered faceted shaft wrapped in a diagonal mega-brace
    exoskeleton, topped by a slender spire."""
    X, Y = _iso(c, r)
    h = 168
    cn = _corners(X, Y, h, HW - 3, (HW - 3) * 0.55)
    out = [_faces(cn, FREMONT, c + r)]
    # diagonal mega-brace exoskeleton: two crossing zig-zags per visible face
    for A, B, Ap, Bp in ((cn["L"], cn["F"], cn["Lp"], cn["Fp"]),
                         (cn["F"], cn["R"], cn["Fp"], cn["Rp"])):
        n = 4
        for flip in (0, 1):
            pts = []
            for i in range(n + 1):
                g = i / n
                lo, hi = _lerp(A, B, g), _lerp(Ap, Bp, g)
                pts.append(hi if (i % 2) == flip else lo)
            path = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            out.append(f'<polyline points="{path}" fill="none" stroke="{PYRAMID[0]}" stroke-width="1.0" opacity="0.8"/>')
    yt = cn["yt"]
    out.append(
        f'<line x1="{X}" y1="{yt}" x2="{X}" y2="{yt-22}" stroke="{PYRAMID[0]}" stroke-width="1.2"/>'
        f'<circle cx="{X}" cy="{yt-22}" r="1.2" fill="{AMBER}" class="beacon"/>'
    )
    return "".join(out), yt - 22


def _bofa(c, r):
    """#5 555 California: dark red-granite monolith, faceted bronze bay-window
    facade, corners rising past a set-back centre crown."""
    X, Y = _iso(c, r)
    h = 158
    bw = HW - 2
    cn = _corners(X, Y, h, bw, bw)            # near-vertical monolith
    out = [_faces(cn, BOFA, c + r)]
    # faceted bay windows: vertical ridges with lit glass on both faces
    for A, B, Ap, Bp, seed in ((cn["L"], cn["F"], cn["Lp"], cn["Fp"], 1),
                              (cn["F"], cn["R"], cn["Fp"], cn["Rp"], 4)):
        for k in range(1, 7):
            g = k / 7
            pb, pt = _lerp(A, B, g), _lerp(Ap, Bp, g)
            lit = (seed + k) % 3 == 0
            out.append(
                f'<line x1="{pb[0]:.1f}" y1="{pb[1]:.1f}" x2="{pt[0]:.1f}" y2="{pt[1]:.1f}" '
                f'stroke="{"#d8a878" if lit else "#23131a"}" stroke-width="1.1" '
                f'opacity="{0.5 if lit else 0.5}"/>'
            )
    # set-back centre: the four corners rise as short piers above a recessed
    # middle parapet (555's notched crown)
    yt = cn["yt"]
    out.append(f'<rect x="{X-bw:.1f}" y="{yt-1:.1f}" width="{2*bw:.1f}" height="3" fill="{BOFA[2]}"/>')
    for cx in (cn["Lp"], cn["Fp"], cn["Rp"]):
        out.append(f'<rect x="{cx[0]-1.6:.1f}" y="{cx[1]-5:.1f}" width="3.2" height="6" fill="{BOFA[0]}"/>')
    return "".join(out), yt - 5


def _coit(c, r):
    """#6 Coit Tower: plain fluted concrete column, arched observation deck
    near the top, almost no taper."""
    X, Y = _iso(c, r)
    h, rad = 86, HW - 4
    ry = rad * HH / HW
    top, mid, dark = COIT
    yt = Y - h
    out = [
        f'<rect x="{X-rad:.1f}" y="{yt:.1f}" width="{2*rad:.1f}" height="{h:.1f}" fill="{mid}"/>',
        _poly([(X - rad, Y), (X + rad, Y), (X + rad, Y + ry), (X - rad, Y + ry)], mid),
        f'<ellipse cx="{X}" cy="{Y+ry:.1f}" rx="{rad:.1f}" ry="{ry:.1f}" fill="{mid}"/>',
        f'<rect x="{X-rad:.1f}" y="{yt:.1f}" width="{rad*0.5:.1f}" height="{h:.1f}" fill="{dark}" opacity="0.35"/>',
    ]
    for k in range(-3, 4):           # flutes
        x = X + k * rad / 3.4
        out.append(f'<line x1="{x:.1f}" y1="{yt+3:.1f}" x2="{x:.1f}" y2="{Y:.1f}" stroke="{dark}" stroke-width="0.5" opacity="0.4"/>')
    # arched observation openings near the top
    for k in (-1, 0, 1):
        ax = X + k * rad * 0.55
        out.append(f'<rect x="{ax-1.3:.1f}" y="{yt+5:.1f}" width="2.6" height="7" rx="1.3" fill="{dark}" opacity="0.65"/>')
    # cap
    out.append(
        f'<rect x="{X-rad-1:.1f}" y="{yt-3:.1f}" width="{2*rad+2:.1f}" height="4" fill="{mid}"/>'
        f'<ellipse cx="{X}" cy="{yt-3:.1f}" rx="{rad+1:.1f}" ry="{ry+0.5:.1f}" fill="{top}"/>'
    )
    return "".join(out), yt - 3


def _ferry(c, r):
    """#7 Ferry Building: long arcaded hall with a central Giralda-style clock
    tower crowned by a pyramidal spire."""
    X, Y = _iso(c, r)
    bw = HW - 1
    # low arcaded base
    base = _faces(_corners(X, Y, 26, bw, bw), FERRY, c + r)
    # clock tower rising from the centre
    tw = bw * 0.42
    cn = _corners(X, Y - 22, 96, tw, tw)
    top, left, right = FERRY
    out = [base, _faces(cn, FERRY, c + r)]
    yt = cn["yt"]
    # clock face high on the front edge
    cy = yt + 24
    out.append(
        f'<circle cx="{X}" cy="{cy:.1f}" r="3.4" fill="#f3efe2" stroke="{right}" stroke-width="0.6"/>'
        f'<line x1="{X}" y1="{cy:.1f}" x2="{X}" y2="{cy-2.4:.1f}" stroke="#2a2018" stroke-width="0.6"/>'
        f'<line x1="{X}" y1="{cy:.1f}" x2="{X+2:.1f}" y2="{cy:.1f}" stroke="#2a2018" stroke-width="0.6"/>'
    )
    # pyramidal spire + cupola
    out.append(
        f'<rect x="{X-tw-1:.1f}" y="{yt-2:.1f}" width="{2*tw+2:.1f}" height="3" fill="{left}"/>'
        + _poly([(X - tw, yt - 2), (X + tw, yt - 2), (X, yt - 20)], top)
        + f'<circle cx="{X}" cy="{yt-20:.1f}" r="1.1" fill="{AMBER}" class="beacon"/>'
    )
    return "".join(out), yt - 20


def _cityhall(c, r):
    """#8 City Hall: Beaux-Arts mass crowned by an enormous gilded dome,
    lantern and finial."""
    X, Y = _iso(c, r)
    bw = HW - 1
    out = [_faces(_corners(X, Y, 40, bw, bw), STONE, c + r)]
    by = Y - 40
    # colonnade hint on the lit face
    for k in range(1, 6):
        g = k / 6
        p = _lerp((X - bw, by), (X, by + bw * HH / HW), g)
        out.append(f'<line x1="{p[0]:.1f}" y1="{p[1]:.1f}" x2="{p[0]:.1f}" y2="{p[1]+8:.1f}" stroke="{STONE[2]}" stroke-width="0.6" opacity="0.5"/>')
    # drum
    dr = bw * 0.5
    out.append(f'<rect x="{X-dr:.1f}" y="{by-12:.1f}" width="{2*dr:.1f}" height="12" fill="{STONE[1]}"/>')
    # gilded dome
    gt, gm, gd = GOLD
    out.append(
        f'<path d="M {X-dr:.1f} {by-12:.1f} Q {X-dr:.1f} {by-34:.1f} {X:.1f} {by-34:.1f} '
        f'Q {X+dr:.1f} {by-34:.1f} {X+dr:.1f} {by-12:.1f} Z" fill="{gm}"/>'
        f'<path d="M {X-dr:.1f} {by-12:.1f} Q {X-dr:.1f} {by-34:.1f} {X:.1f} {by-34:.1f} '
        f'L {X:.1f} {by-12:.1f} Z" fill="{gt}"/>'
        # lantern + finial
        f'<rect x="{X-2:.1f}" y="{by-40:.1f}" width="4" height="6" fill="{gm}"/>'
        f'<line x1="{X}" y1="{by-40:.1f}" x2="{X}" y2="{by-46:.1f}" stroke="{gd}" stroke-width="1"/>'
        f'<circle cx="{X}" cy="{by-46:.1f}" r="1.4" fill="{WARM_HI}" class="beacon"/>'
    )
    return "".join(out), by - 46


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

    # The famous ten: tall hero towers crown the busiest days; the shorter
    # civic icons sit on mid-tier days spread across the year so their height
    # still reads sensibly.
    lvl4 = sorted(
        (d["contributionCount"], c, r) for c, r, d in cells
        if _level(d["contributionCount"], q) == 4
    )
    landmarks = {}
    heroes = [_salesforce, _sutro, _transamerica, _fremont, _bofa]
    for i, (_, c, r) in enumerate(reversed(lvl4)):
        if i < len(heroes):
            landmarks[(c, r)] = heroes[i]
    mids = [(c, r) for c, r, d in cells
            if _level(d["contributionCount"], q) in (2, 3) and (c, r) not in landmarks]
    for fn, col in zip((_cityhall, _ferry, _coit), (13, 26, 40)):
        if mids:
            best = min(mids, key=lambda cr: abs(cr[0] - col))
            landmarks[best] = fn
            mids.remove(best)

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
        shadows.append(_shadow(c, r, h if (c, r) not in landmarks else 130))

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
<text x="26" y="56" font-size="10" fill="{FG}">EVERY DAY A LOT · PAINTED LADIES TO HIGH-RISES AS COMMITS RISE · PEAKS BECOME LANDMARKS · ROLLING 365D</text>
<text x="{W-26}" y="36" text-anchor="end" font-size="13" fill="{AMBER}" font-weight="700">{total:,} CONTRIBUTIONS</text>
<text x="{W-26}" y="56" text-anchor="end" font-size="10" fill="{FG}">ACTIVE {active}/365 · STREAK {streak}D · PEAK {peak_day['contributionCount']}</text>
<text x="40" y="{legend_y-6}" font-size="8" fill="{MUTED}">QUIET</text>
{swatches}
<text x="{40+5*16+6}" y="{legend_y+8}" font-size="8" fill="{MUTED}">BUSY · EST. {created.year}</text>
<text x="{W-26}" y="{H-14}" text-anchor="end" font-size="8" fill="{MUTED}" letter-spacing="0.5">LANDMARKS · SALESFORCE · TRANSAMERICA · SUTRO · 181 FREMONT · 555 CALIFORNIA · COIT · FERRY · CITY HALL</text>
<rect width="{W}" height="{H}" rx="14" fill="none" stroke="{BORDER}"/>
</svg>"""
    write_svg("city.svg", svg)
