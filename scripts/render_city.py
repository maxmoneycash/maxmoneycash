"""Isometric contribution city over a painted San Francisco dusk.

A year of GitHub contributions as window-skinned buildings rising out of
the bay in front of the SF skyline artwork (assets/sf-bg.jpg, embedded).
Still reads as a contribution graph: 53 weeks x 7 days, mint intensity
ramp, month/weekday axes, peak-day pennant, streak highlights, and a
WPA-park-poster legend.
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

# top / left / right face colors per intensity level (mint ramp at dusk)
FACES = [
    ("#141b25", "#10161e", "#0c1118"),
    ("#0d4f43", "#0a3a32", "#072a24"),
    ("#0f8a6e", "#0b6852", "#084d3d"),
    ("#16c79a", "#109573", "#0b6b53"),
    ("#97fce4", "#5fd9bd", "#3aa78f"),
]
HEIGHTS = [2, 14, 26, 40, 56]

WIN_LIT = "#ffd479"
WIN_DARK = "#0a1119"
AMBER = "#ffb454"
MINT = "#16c79a"
MINT_HI = "#97fce4"
FG = "#9fb2c8"
MUTED = "#7d8da1"
BORDER = "#1c2430"

# WPA poster palette
P_CREAM = "#ead9b0"
P_GREEN = "#2c4a3b"
P_RUST = "#c46a3d"
P_INK = "#22302a"

W, H = 940, 640
HW, HH = 8, 4  # iso half-width / half-height
X0, Y0 = 270, 392


def _level(count, q):
    if count <= 0:
        return 0
    for i, t in enumerate(q):
        if count <= t:
            return i + 1
    return 4


def _poster(total, est_year):
    x, y, w, h = 26, 452, 192, 164
    s = [
        f'<g filter="url(#drop)">',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{P_CREAM}"/>',
        f'<rect x="{x + 5}" y="{y + 5}" width="{w - 10}" height="{h - 10}" rx="3" '
        f'fill="none" stroke="{P_GREEN}" stroke-width="2"/>',
        # header band
        f'<rect x="{x + 5}" y="{y + 5}" width="{w - 10}" height="30" fill="{P_GREEN}"/>',
        f'<text x="{x + w / 2}" y="{y + 17}" text-anchor="middle" font-size="8" '
        f'letter-spacing="2" fill="{P_CREAM}">SAN FRANCISCO · CALIF.</text>',
        f'<text x="{x + w / 2}" y="{y + 30}" text-anchor="middle" font-size="11" '
        f'font-weight="700" letter-spacing="1.5" fill="{P_CREAM}">COMMIT DISTRICT</text>',
        # WPA sunset motif: amber sun, rays, green hills
        f'<clipPath id="postclip"><rect x="{x + 9}" y="{y + 39}" width="{w - 18}" height="56"/></clipPath>',
        f'<g clip-path="url(#postclip)">',
        f'<rect x="{x + 9}" y="{y + 39}" width="{w - 18}" height="56" fill="#d8b889"/>',
        f'<circle cx="{x + w / 2}" cy="{y + 95}" r="26" fill="{AMBER}"/>',
    ]
    for i in range(7):
        ang = -90 + i * 26 - 78
        s.append(
            f'<rect x="{x + w / 2 - 1.5}" y="{y + 50}" width="3" height="22" fill="{AMBER}" '
            f'opacity="0.55" transform="rotate({ang} {x + w / 2} {y + 95})"/>'
        )
    s += [
        f'<polygon points="{x + 9},{y + 95} {x + 60},{y + 70} {x + 110},{y + 95}" fill="{P_GREEN}"/>',
        f'<polygon points="{x + 80},{y + 95} {x + 140},{y + 64} {x + w - 9},{y + 95}" fill="#3a5f4b"/>',
        f'</g>',
        # swatch legend
        f'<text x="{x + 16}" y="{y + 116}" font-size="8" fill="{P_INK}">FEWER</text>',
    ]
    for i in range(5):
        s.append(
            f'<rect x="{x + 52 + i * 17}" y="{y + 107}" width="13" height="11" rx="2" '
            f'fill="{FACES[i][0]}" stroke="{P_INK}" stroke-width="0.8"/>'
        )
    s += [
        f'<text x="{x + 52 + 5 * 17 + 5}" y="{y + 116}" font-size="8" fill="{P_INK}">MORE</text>',
        f'<line x1="{x + 16}" y1="{y + 128}" x2="{x + w - 16}" y2="{y + 128}" '
        f'stroke="{P_INK}" stroke-width="0.8"/>',
        f'<text x="{x + w / 2}" y="{y + 142}" text-anchor="middle" font-size="8" '
        f'fill="{P_INK}">EST. {est_year} · COMMITS SERVED DAILY</text>',
        f'<text x="{x + w / 2}" y="{y + 154}" text-anchor="middle" font-size="9" '
        f'font-weight="700" fill="{P_RUST}">{total:,} THIS YEAR</text>',
        f'</g>',
    ]
    return "".join(s)


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

    # current streak cells (consecutive active days ending today)
    streak = 0
    for c in reversed(counts):
        if c > 0:
            streak += 1
        else:
            break
    streak_dates = {d["date"] for d in days_flat[len(days_flat) - streak:]} if streak else set()
    active = sum(1 for c in counts if c > 0)
    peak_day = max(days_flat, key=lambda d: d["contributionCount"])

    bg64 = base64.b64encode((ROOT / "assets" / "sf-bg.jpg").read_bytes()).decode()

    cells = []
    for c, w in enumerate(weeks):
        for r, d in enumerate(w["contributionDays"]):
            cells.append((c + r, c, r, d))
    cells.sort(key=lambda t: t[0])

    city, peak_pos = [], None
    for depth, c, r, d in cells:
        count = d["contributionCount"]
        lvl = _level(count, q)
        X = X0 + (c - r) * HW
        Y = Y0 + (c + r) * HH
        top, left, right = FACES[lvl]
        h = HEIGHTS[lvl]
        if lvl >= 2:
            h += (c * 31 + r * 17) % 7
        if lvl == 0:
            city.append(
                f'<polygon points="{X},{Y - HH} {X + HW},{Y} {X},{Y + HH} {X - HW},{Y}" '
                f'fill="{top}" fill-opacity="0.85" stroke="#1a2330" stroke-width="0.3"/>'
            )
            continue
        yt = Y - h
        if lvl >= 3:
            city.append(
                f'<ellipse cx="{X}" cy="{Y + 2}" rx="{HW + 6}" ry="4" fill="{MINT}" opacity="0.10"/>'
            )
        outline = (
            f' stroke="{AMBER}" stroke-width="0.9"' if d["date"] in streak_dates else ""
        )
        city.append(
            f'<polygon points="{X - HW},{yt} {X},{yt + HH} {X},{Y + HH} {X - HW},{Y}" fill="{left}"/>'
            f'<polygon points="{X},{yt + HH} {X + HW},{yt} {X + HW},{Y} {X},{Y + HH}" fill="{right}"/>'
            f'<polygon points="{X},{yt - HH} {X + HW},{yt} {X},{yt + HH} {X - HW},{yt}" fill="{top}"{outline}/>'
        )
        if h >= 24:
            t = 5
            while t < h - 5:
                for f in (0.3, 0.68):
                    lit = (c * 13 + r * 7 + t) % 5 < 2
                    city.append(
                        f'<rect x="{X - HW + f * HW - 0.9:.1f}" y="{yt + HH * f + t:.1f}" '
                        f'width="1.8" height="2.6" fill="{WIN_LIT if lit else WIN_DARK}" '
                        f'opacity="{0.85 if lit else 0.55}"/>'
                    )
                    lit2 = (c * 7 + r * 11 + t) % 4 == 0
                    city.append(
                        f'<rect x="{X + f * HW - 0.9:.1f}" y="{yt + HH - f * HH + t:.1f}" '
                        f'width="1.8" height="2.6" fill="{WIN_LIT if lit2 else WIN_DARK}" '
                        f'opacity="{0.9 if lit2 else 0.45}"/>'
                    )
                t += 7
        if lvl == 4:
            city.append(
                f'<line x1="{X}" y1="{yt - HH}" x2="{X}" y2="{yt - HH - 9}" '
                f'stroke="#5a6b80" stroke-width="0.8"/>'
                f'<circle cx="{X}" cy="{yt - HH - 10}" r="1.3" fill="#ff5f56" class="beacon" '
                f'style="animation-delay:{(c * 7 + r) % 20 * 0.15:.2f}s"/>'
            )
        if d["date"] == peak_day["date"]:
            peak_pos = (X, yt - HH, count, d["date"])

    # peak-day pennant
    pennant = ""
    if peak_pos:
        px, py, pc, pdate = peak_pos
        label = f"PEAK {pc} · {datetime.date.fromisoformat(pdate):%b %d}".upper()
        lw = len(label) * 5.6 + 14
        pennant = (
            f'<line x1="{px}" y1="{py}" x2="{px}" y2="{py - 30}" stroke="{AMBER}" stroke-width="1"/>'
            f'<polygon points="{px},{py - 30} {px + 16},{py - 26} {px},{py - 22}" fill="{AMBER}"/>'
            f'<rect x="{px - lw / 2}" y="{py - 50}" width="{lw}" height="15" rx="3" '
            f'fill="#070b10" fill-opacity="0.8" stroke="{AMBER}" stroke-width="0.6"/>'
            f'<text x="{px}" y="{py - 39}" text-anchor="middle" font-size="9" '
            f'fill="{AMBER}" font-weight="700">{label}</text>'
        )

    # month labels along the top edge (r=0), weekday labels along the left (c=0)
    axes = []
    seen_month = None
    for c, w in enumerate(weeks):
        d0 = datetime.date.fromisoformat(w["contributionDays"][0]["date"])
        if d0.month != seen_month:
            seen_month = d0.month
            if c > 0:
                X = X0 + c * HW
                Y = Y0 + c * HH
                mon = f"{d0:%b}".upper()
                axes.append(
                    f'<text x="{X + 4}" y="{Y - HH - 6}" font-size="8" fill="{MUTED}" '
                    f'opacity="0.9">{mon}</text>'
                )
    for r, day in ((1, "MON"), (3, "WED"), (5, "FRI")):
        X = X0 - r * HW
        Y = Y0 + r * HH
        axes.append(
            f'<text x="{X - HW - 6}" y="{Y + 3}" text-anchor="end" font-size="8" '
            f'fill="{MUTED}" opacity="0.9">{day}</text>'
        )

    created = datetime.datetime.fromisoformat(
        gh["user"]["created_at"].replace("Z", "+00:00")
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <clipPath id="card"><rect width="{W}" height="{H}" rx="14"/></clipPath>
  <linearGradient id="seat" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#070b10" stop-opacity="0"/>
    <stop offset="0.55" stop-color="#070b10" stop-opacity="0.32"/>
    <stop offset="1" stop-color="#070b10" stop-opacity="0.72"/>
  </linearGradient>
  <filter id="drop" x="-20%" y="-20%" width="140%" height="140%">
    <feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#000" flood-opacity="0.5"/>
  </filter>
  <style>
    @keyframes beacon {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.15; }} }}
    .beacon {{ animation: beacon 2.6s ease-in-out infinite; }}
  </style>
</defs>
<g clip-path="url(#card)">
  <image href="data:image/jpeg;base64,{bg64}" x="0" y="0" width="{W}" height="{H}" preserveAspectRatio="xMidYMid slice"/>
  <rect x="0" y="{Y0 - 80}" width="{W}" height="{H - Y0 + 80}" fill="url(#seat)"/>
</g>
{"".join(axes)}
{"".join(city)}
{pennant}
<text x="26" y="36" font-size="14" font-weight="700" fill="{MINT_HI}" letter-spacing="2">SAN FRANCISCO · CONTRIBUTION DISTRICT</text>
<text x="26" y="56" font-size="10" fill="{FG}">53 WEEKS × 7 DAYS · EVERY BUILDING IS A DAY OF COMMITS · ROLLING 365D</text>
<text x="{W - 26}" y="36" text-anchor="end" font-size="13" fill="{AMBER}" font-weight="700">{total:,} CONTRIBUTIONS</text>
<text x="{W - 26}" y="56" text-anchor="end" font-size="10" fill="{FG}">ACTIVE {active}/365 · STREAK {streak}D · PEAK {peak_day['contributionCount']}</text>
{_poster(total, created.year)}
<rect width="{W}" height="{H}" rx="14" fill="none" stroke="{BORDER}"/>
</svg>"""
    write_svg("city.svg", svg)
