"""Holdings showcase: each repo as a card with a live app screenshot banner,
a 52-week commit sparkline, $ticker, language pill, and stats. Also rewrites
the README holdings block (between <!-- HOLDINGS:START/END -->) from the same
config, so adding a repo is a one-line edit to scripts/showcase.json.

Screenshots live in assets/shots/<repo>.jpg (auto-captured by screenshot_apps.sh
for entries with a `url`, or hand-supplied). Commit activity is the GitHub REST
commit_activity series (retries on 202). Supports cross-org repos via `owner`.
"""
import base64
import datetime
import json
import pathlib

from common import LOGIN, THEME, esc, gh_api, write_svg

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHOTS = ROOT / "assets" / "shots"
README = ROOT / "README.md"
MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"

LANG_COLORS = {
    "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Python": "#3572A5",
    "Move": "#4a90e2", "Rust": "#dea584", "HTML": "#e34c26", "Solidity": "#AA6746",
    "Svelte": "#ff3e00", "C++": "#f34b7d", "Go": "#00ADD8",
}

SHOWCASE = json.loads((ROOT / "scripts" / "showcase.json").read_text())["holdings"]
W = 460


def owner_of(h):
    return h.get("owner", LOGIN)


def link_of(h):
    return h.get("link") or h.get("url") or f"https://github.com/{owner_of(h)}/{h['repo']}"


def ago(iso):
    d = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    days = (datetime.datetime.now(datetime.timezone.utc) - d).days
    if days < 1:
        return "today"
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def weekly_commits(owner, repo):
    for _ in range(3):
        try:
            data = gh_api(f"/repos/{owner}/{repo}/stats/commit_activity")
        except Exception:
            data = None
        if isinstance(data, list) and data:
            return [w.get("total", 0) for w in data[-52:]]
    return [0] * 52


def render_card(h):
    t = THEME
    repo, owner = h["repo"], owner_of(h)
    try:
        r = gh_api(f"/repos/{owner}/{repo}")
    except Exception:
        return None
    lang = r.get("language") or "—"
    lang_color = LANG_COLORS.get(lang, "#8b949e")
    desc = (r.get("description") or "").strip()
    weekly = weekly_commits(owner, repo)
    commits52 = sum(weekly)
    ticker = "$" + "".join(c for c in repo.upper() if c.isalnum())[:7]
    label = link_of(h).replace("https://", "").replace("http://", "").rstrip("/")
    if len(label) > 36:
        label = label[:35] + "…"

    shot = SHOTS / f"{repo}.jpg"
    banner_h = 172
    H = banner_h + 130
    cx = W // 2

    parts = []
    # ---- banner: live screenshot, or a generated placeholder so it never looks broken ----
    if shot.exists():
        b64 = base64.b64encode(shot.read_bytes()).decode()
        parts.append(
            f'<image href="data:image/jpeg;base64,{b64}" x="0" y="0" width="{W}" height="{banner_h}" '
            f'preserveAspectRatio="xMidYMid slice" clip-path="url(#bclip)"/>'
        )
    else:
        parts.append(
            f'<rect x="0" y="0" width="{W}" height="{banner_h}" fill="url(#ph)" clip-path="url(#bclip)"/>'
            f'<text x="{cx}" y="{banner_h // 2 + 15}" text-anchor="middle" font-size="46" font-weight="800" '
            f'fill="{lang_color}" opacity="0.15">{ticker}</text>'
            f'<text x="{cx}" y="{banner_h - 24}" text-anchor="middle" font-size="9.5" fill="{t["muted"]}" '
            f'letter-spacing="2.5">LIVE PREVIEW SOON</text>'
        )
    # bottom scrim + url label + language accent bar
    parts.append(
        f'<rect x="0" y="{banner_h - 48}" width="{W}" height="48" fill="url(#fade)" clip-path="url(#bclip)"/>'
        f'<text x="{W - 14}" y="{banner_h - 13}" text-anchor="end" font-size="9.5" fill="#dbe6f0" opacity="0.9">{esc(label)} ↗</text>'
        f'<rect x="0" y="{banner_h - 2}" width="{W}" height="2" fill="{lang_color}" opacity="0.9"/>'
    )

    # ---- title + ticker + language pill ----
    ty = banner_h + 32
    pill_w = len(lang) * 7 + 28
    parts.append(
        f'<text x="22" y="{ty}" font-size="18" font-weight="700" fill="{t["phosphor"]}">{esc(repo)}</text>'
        f'<text x="22" y="{ty + 17}" font-size="9.5" fill="{t["muted"]}" letter-spacing="1.5">{ticker}</text>'
        f'<rect x="{W - 22 - pill_w}" y="{ty - 15}" width="{pill_w}" height="21" rx="10.5" '
        f'fill="#161b22" stroke="{lang_color}" stroke-opacity="0.5"/>'
        f'<circle cx="{W - 22 - pill_w + 13}" cy="{ty - 4.5}" r="4" fill="{lang_color}"/>'
        f'<text x="{W - 29}" y="{ty - 0.5}" text-anchor="end" font-size="10" fill="{t["fg"]}">{esc(lang)}</text>'
    )
    if desc:
        if len(desc) > 60:
            desc = desc[:57] + "…"
        parts.append(f'<text x="22" y="{ty + 37}" font-size="11.5" fill="#9fb0c0">{esc(desc)}</text>')

    # ---- 52-week commit sparkline with end-dot ----
    sx, sy, sh_, sw = 22, ty + 51, 28, W - 44
    wmax = max(max(weekly), 1)
    coords = [(sx + i * sw / 51, sy + sh_ - sh_ * v / wmax) for i, v in enumerate(weekly)]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    ex, ey = coords[-1]
    parts.append(
        f'<polygon points="{sx},{sy + sh_} {pts} {sx + sw},{sy + sh_}" fill="url(#spk)"/>'
        f'<polyline points="{pts}" fill="none" stroke="{t["phosphor"]}" stroke-width="1.5"/>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="2.6" fill="{t["phosphor"]}"/>'
        f'<text x="{sx}" y="{sy + sh_ + 17}" font-size="8.5" fill="{t["muted"]}" letter-spacing="1.5">52-WEEK COMMITS</text>'
        f'<text x="{W - 22}" y="{sy + sh_ + 17}" text-anchor="end" font-size="10.5" fill="#9fb0c0">'
        f'<tspan fill="{t["phosphor"]}" font-weight="700">{commits52}</tspan> commits  ·  ★ {r.get("stargazers_count", 0)}  ·  {ago(r["pushed_at"])}</text>'
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <clipPath id="bclip"><path d="M0,12 Q0,0 12,0 H{W - 12} Q{W},0 {W},12 V{banner_h} H0 Z"/></clipPath>
  <linearGradient id="cbg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#0d1117"/><stop offset="1" stop-color="#0a0f16"/>
  </linearGradient>
  <linearGradient id="ph" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#11161d"/><stop offset="1" stop-color="{lang_color}" stop-opacity="0.12"/>
  </linearGradient>
  <linearGradient id="spk" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{THEME['phosphor']}" stop-opacity="0.35"/>
    <stop offset="1" stop-color="{THEME['phosphor']}" stop-opacity="0.02"/>
  </linearGradient>
  <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#0d1117" stop-opacity="0"/><stop offset="1" stop-color="#0d1117" stop-opacity="0.9"/>
  </linearGradient>
</defs>
<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="url(#cbg)" stroke="{THEME['border']}"/>
{"".join(parts)}
</svg>"""
    write_svg(f"holding-{repo}.svg", svg)
    return repo


def rewrite_readme_block(rendered):
    start, end = "<!-- HOLDINGS:START -->", "<!-- HOLDINGS:END -->"
    text = README.read_text()
    if start not in text or end not in text:
        return
    cells = "\n".join(
        f'<a href="{link_of(h)}"><img src="./assets/holding-{h["repo"]}.svg" width="400" alt="{esc(h["repo"])}"/></a>'
        for h in SHOWCASE if h["repo"] in rendered
    )
    block = f"{start}\n<p align=\"center\">\n{cells}\n</p>\n{end}"
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    README.write_text(head + block + tail)


def render(gh=None, tokens=None):
    rendered = [repo for h in SHOWCASE if (repo := render_card(h))]
    rewrite_readme_block(rendered)
    print(f"rendered {len(rendered)} holding cards + README block")
    return rendered


if __name__ == "__main__":
    render()
