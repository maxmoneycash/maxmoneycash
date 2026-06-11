"""Per-year GitHub contribution heatmaps (GraphQL), GitHub-dark palette."""
import datetime

from common import LOGIN, THEME, gh_graphql, write_svg

# 9-step ramp: zero → GitHub greens → phosphor mint → white-hot, so heavy
# 50-100-commit days don't flatten into the same shade as a 10-commit day.
PALETTE = [
    "#161b22", "#0a3a26", "#0e5230", "#15703c", "#229246",
    "#39d353", "#5ce96f", "#97fce4", "#eafffa",
]
# nonzero percentile cuts for levels 1..8
CUTS = (0.13, 0.27, 0.42, 0.57, 0.72, 0.85, 0.95)
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


def _level(count, q):
    if count <= 0:
        return 0
    for i, threshold in enumerate(q):
        if count <= threshold:
            return i + 1
    return len(q) + 1


def render_year(year):
    today = datetime.date.today()
    to = (
        f"{today.isoformat()}T23:59:59Z"
        if year == today.year
        else f"{year}-12-31T23:59:59Z"
    )
    cal = gh_graphql(
        QUERY,
        {"login": LOGIN, "from": f"{year}-01-01T00:00:00Z", "to": to},
    )["user"]["contributionsCollection"]["contributionCalendar"]
    ytd = " · ytd" if year == today.year else ""

    counts = sorted(
        d["contributionCount"]
        for w in cal["weeks"]
        for d in w["contributionDays"]
        if d["contributionCount"] > 0
    )
    if counts:
        q = [counts[min(int(len(counts) * p), len(counts) - 1)] for p in CUTS]
    else:
        q = list(range(1, len(CUTS) + 1))

    # Fixed 53-column grid so every year's card has identical dimensions
    # (the current year would otherwise be narrower and scale up larger).
    # Days after today render as faint empty boxes: the rest of the year.
    COLS = 53
    cell, gap, pad_x, pad_y = 11, 3, 18, 40
    W = pad_x * 2 + COLS * (cell + gap)
    H = pad_y + 7 * (cell + gap) + 14

    counts = {
        d["date"]: d["contributionCount"]
        for w in cal["weeks"]
        for d in w["contributionDays"]
    }
    jan1 = datetime.date(year, 1, 1)
    grid_start = jan1 - datetime.timedelta(days=(jan1.weekday() + 1) % 7)

    rects = []
    d = jan1
    while d.year == year:
        offset = (d - grid_start).days
        col, row = offset // 7, offset % 7
        if col >= COLS:
            break
        x = pad_x + col * (cell + gap)
        y = pad_y + row * (cell + gap)
        if d > today:
            rects.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" '
                f'fill="{PALETTE[0]}" opacity="0.45"/>'
            )
        else:
            lvl = _level(counts.get(d.isoformat(), 0), q)
            rects.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" '
                f'fill="{PALETTE[lvl]}"/>'
            )
        d += datetime.timedelta(days=1)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<rect width="{W}" height="{H}" rx="10" fill="{THEME['bg']}" stroke="{THEME['border']}"/>
<text x="{pad_x}" y="24" font-size="13" fill="{THEME['fg']}">
  <tspan fill="{THEME['green']}" font-weight="700">{cal['totalContributions']:,}</tspan> contributions in {year}{ytd}
</text>
<text x="{W - pad_x - len(PALETTE) * 11 - 38}" y="23" text-anchor="end" font-size="9" fill="{THEME['muted']}">less</text>
{"".join(f'<rect x="{W - pad_x - 30 - (len(PALETTE) - i) * 11}" y="14" width="8" height="8" rx="2" fill="{c}"/>' for i, c in enumerate(PALETTE))}
<text x="{W - pad_x}" y="23" text-anchor="end" font-size="9" fill="{THEME['muted']}">more</text>
{"".join(rects)}
</svg>"""
    write_svg(f"heatmap-{year}.svg", svg)


def render(gh=None, tokens=None):
    current = datetime.date.today().year
    for year in range(current - 4, current + 1):
        render_year(year)
