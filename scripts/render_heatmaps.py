"""Per-year GitHub contribution heatmaps (GraphQL), GitHub-dark palette."""
import datetime

from common import LOGIN, THEME, gh_graphql, write_svg

PALETTE = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]
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
    return 4


def render_year(year):
    cal = gh_graphql(
        QUERY,
        {
            "login": LOGIN,
            "from": f"{year}-01-01T00:00:00Z",
            "to": f"{year}-12-31T23:59:59Z",
        },
    )["user"]["contributionsCollection"]["contributionCalendar"]

    counts = sorted(
        d["contributionCount"]
        for w in cal["weeks"]
        for d in w["contributionDays"]
        if d["contributionCount"] > 0
    )
    if counts:
        q = [counts[int(len(counts) * p)] for p in (0.25, 0.5, 0.75)]
    else:
        q = [1, 2, 3]

    cell, gap, pad_x, pad_y = 11, 3, 18, 40
    weeks = cal["weeks"]
    W = pad_x * 2 + len(weeks) * (cell + gap)
    H = pad_y + 7 * (cell + gap) + 14

    rects = []
    for wi, w in enumerate(weeks):
        for d in w["contributionDays"]:
            day = datetime.date.fromisoformat(d["date"]).weekday()
            # GitHub weeks start Sunday
            row = (day + 1) % 7
            lvl = _level(d["contributionCount"], q)
            x = pad_x + wi * (cell + gap)
            y = pad_y + row * (cell + gap)
            rects.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" '
                f'fill="{PALETTE[lvl]}"/>'
            )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<rect width="{W}" height="{H}" rx="10" fill="{THEME['bg']}" stroke="{THEME['border']}"/>
<text x="{pad_x}" y="24" font-size="12" fill="{THEME['fg']}">
  <tspan fill="{THEME['green']}" font-weight="700">{cal['totalContributions']:,}</tspan> contributions in {year}
</text>
{"".join(rects)}
</svg>"""
    write_svg(f"heatmap-{year}.svg", svg)


def render(gh=None, tokens=None):
    current = datetime.date.today().year
    for year in range(current - 3, current):
        render_year(year)
