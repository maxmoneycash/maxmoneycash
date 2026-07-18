"""Per-year GitHub contribution heatmaps, GitHub-dark palette."""
import datetime
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

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

PUBLIC_COUNT_RE = re.compile(
    r'^\s*(?P<count>\d{1,3}(?:,\d{3})+|\d+|No) contributions? on\b',
    re.IGNORECASE,
)


class PublicCalendarHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells = []
        self.tooltips = {}
        self._tooltip_for = None
        self._tooltip_text = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "td" and "data-date" in values:
            self.cells.append((values.get("data-date"), values.get("id")))
        elif tag == "tool-tip" and values.get("for"):
            self._tooltip_for = values["for"]
            self._tooltip_text = []

    def handle_data(self, data):
        if self._tooltip_for is not None:
            self._tooltip_text.append(data)

    def handle_endtag(self, tag):
        if tag != "tool-tip" or self._tooltip_for is None:
            return
        text = "".join(self._tooltip_text).strip()
        self.tooltips.setdefault(self._tooltip_for, []).append(text)
        self._tooltip_for = None
        self._tooltip_text = []


def parse_public_calendar(markup, through=None):
    """Parse GitHub's own bounded public contribution-calendar fragment."""
    parser = PublicCalendarHTMLParser()
    parser.feed(markup)
    parser.close()

    validated_cells = []
    for date_value, cell_id in parser.cells:
        if not cell_id:
            raise RuntimeError("GitHub public contribution calendar has a cell without an id")
        if not isinstance(date_value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
            raise RuntimeError("GitHub public contribution calendar has an invalid date")
        try:
            parsed_date = datetime.datetime.strptime(date_value, "%Y-%m-%d").date()
        except ValueError as error:
            raise RuntimeError("GitHub public contribution calendar has an invalid date") from error
        if parsed_date.isoformat() != date_value:
            raise RuntimeError("GitHub public contribution calendar has an invalid date")
        validated_cells.append((date_value, cell_id, parsed_date))

    through_date = None
    lower_date = None
    if through is not None:
        if not isinstance(through, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", through):
            raise RuntimeError("GitHub public contribution calendar has an invalid upper bound")
        try:
            through_date = datetime.datetime.strptime(through, "%Y-%m-%d").date()
        except ValueError as error:
            raise RuntimeError("GitHub public contribution calendar has an invalid upper bound") from error
        if through_date.isoformat() != through:
            raise RuntimeError("GitHub public contribution calendar has an invalid upper bound")
        lower_date = datetime.date(through_date.year, 1, 1)

    dates = [date_value for date_value, _, _ in validated_cells]
    cell_ids = [cell_id for _, cell_id, _ in validated_cells]
    if len(dates) != len(set(dates)) or len(cell_ids) != len(set(cell_ids)):
        raise RuntimeError("GitHub public contribution calendar contains duplicate days")

    all_cell_ids = set(cell_ids)
    eligible = [
        (date_value, cell_id)
        for date_value, cell_id, parsed_date in validated_cells
        if (lower_date is None or parsed_date >= lower_date)
        and (through_date is None or parsed_date <= through_date)
    ]
    dates = [date for date, _ in eligible]
    cell_ids = [cell_id for _, cell_id in eligible]
    if not eligible:
        raise RuntimeError("GitHub public contribution calendar returned no days")

    days = []
    for date, cell_id in eligible:
        tooltip_rows = parser.tooltips.get(cell_id, [])
        if len(tooltip_rows) != 1:
            raise RuntimeError("GitHub public contribution calendar has a missing or duplicate tooltip")
        match = PUBLIC_COUNT_RE.match(tooltip_rows[0])
        if match is None:
            raise RuntimeError("GitHub public contribution calendar has an invalid tooltip")
        raw_count = match.group("count")
        count = 0 if raw_count.lower() == "no" else int(raw_count.replace(",", ""))
        days.append({"date": date, "contributionCount": count})

    for tooltip_id, rows in parser.tooltips.items():
        if tooltip_id not in all_cell_ids and any(PUBLIC_COUNT_RE.match(row) for row in rows):
            raise RuntimeError("GitHub public contribution calendar has an orphan tooltip")
    return {
        "totalContributions": sum(day["contributionCount"] for day in days),
        "weeks": [{"contributionDays": days}],
    }


def fetch_public_calendar(year, through):
    query = urllib.parse.urlencode({
        "from": f"{year}-01-01",
        "to": through,
    })
    request = urllib.request.Request(
        f"https://github.com/users/{urllib.parse.quote(LOGIN)}/contributions?{query}",
        headers={"Accept": "text/html", "User-Agent": LOGIN},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        markup = response.read().decode("utf-8", errors="replace")
    return parse_public_calendar(markup, through=through)


def is_github_limit_error(error):
    """Accept only the structured GraphQL limit types we can safely bypass."""
    errors = error.args[0] if error.args else None
    allowed_types = {"RESOURCE_LIMITS_EXCEEDED", "RATE_LIMITED"}
    return (
        isinstance(errors, list)
        and bool(errors)
        and all(
            isinstance(item, dict) and item.get("type") in allowed_types
            for item in errors
        )
    )


def _level(count, q):
    if count <= 0:
        return 0
    for i, threshold in enumerate(q):
        if count <= threshold:
            return i + 1
    return len(q) + 1


def render_year(year):
    today = datetime.date.today()
    through = today.isoformat() if year == today.year else f"{year}-12-31"
    try:
        cal = gh_graphql(
            QUERY,
            {
                "login": LOGIN,
                "from": f"{year}-01-01T00:00:00Z",
                "to": f"{through}T23:59:59Z",
            },
        )["user"]["contributionsCollection"]["contributionCalendar"]
    except RuntimeError as error:
        if not is_github_limit_error(error):
            raise
        cal = fetch_public_calendar(year, through)
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
