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

    shot = SHOTS / f"{repo}.jpg"
    has_shot = shot.exists()
    banner_h = 150 if has_shot else 0
    H = banner_h + 168

    parts = []
    if has_shot:
        b64 = base64.b64encode(shot.read_bytes()).decode()
        label = link_of(h).replace("https://", "").replace("http://", "")
        if len(label) > 34:
            label = label[:33] + "…"
        parts.append(
            f'<clipPath id="bclip"><rect x="0" y="0" width="{W}" height="{banner_h}" rx="12"/></clipPath>'
            f'<image href="data:image/jpeg;base64,{b64}" x="0" y="0" width="{W}" height="{banner_h}" '
            f'preserveAspectRatio="xMidYMid slice" clip-path="url(#bclip)"/>'
            f'<rect x="0" y="{banner_h - 40}" width="{W}" height="40" fill="url(#fade)"/>'
            f'<rect x="0" y="0" width="{W}" height="{banner_h}" rx="12" fill="none" stroke="{t["border"]}"/>'
            f'<text x="{W - 12}" y="{banner_h - 12}" text-anchor="end" font-size="9" '
            f'fill="#cdd9e5" opacity="0.85">{esc(label)} ↗</text>'
        )
    py = banner_h + 30

    ticker = "$" + "".join(c for c in repo.upper() if c.isalnum())[:6]
    parts.append(
        f'<text x="20" y="{py}" font-size="17" font-weight="700" fill="{t["phosphor"]}">{esc(repo)}</text>'
        f'<text x="{20 + len(repo) * 10.5 + 12}" y="{py}" font-size="10" fill="{t["muted"]}">{ticker}</text>'
        f'<g><rect x="{W - 20 - (len(lang) * 7 + 26)}" y="{py - 15}" width="{len(lang) * 7 + 26}" height="20" rx="10" '
        f'fill="{t["panel"]}" stroke="{lang_color}" stroke-opacity="0.6"/>'
        f'<circle cx="{W - 20 - (len(lang) * 7 + 26) + 13}" cy="{py - 5}" r="4" fill="{lang_color}"/>'
        f'<text x="{W - 26}" y="{py - 1}" text-anchor="end" font-size="10" fill="{t["fg"]}">{esc(lang)}</text></g>'
    )
    if desc:
        if len(desc) > 64:
            desc = desc[:61] + "..."
        parts.append(f'<text x="20" y="{py + 22}" font-size="11.5" fill="{t["fg"]}">{esc(desc)}</text>')

    sx, sy, sh_, sw = 20, py + 38, 38, W - 40
    wmax = max(max(weekly), 1)
    pts = " ".join(f"{sx + i * sw / 51:.1f},{sy + sh_ - sh_ * v / wmax:.1f}" for i, v in enumerate(weekly))
    parts.append(
        f'<polygon points="{sx},{sy + sh_} {pts} {sx + sw},{sy + sh_}" fill="url(#spk)"/>'
        f'<polyline points="{pts}" fill="none" stroke="{t["phosphor"]}" stroke-width="1.4"/>'
        f'<text x="{sx}" y="{sy + sh_ + 15}" font-size="9" fill="{t["muted"]}">52-WEEK COMMIT FLOW</text>'
        f'<text x="{W - 20}" y="{sy + sh_ + 15}" text-anchor="end" font-size="11" fill="{t["fg"]}">'
        f'<tspan fill="{t["phosphor"]}" font-weight="700">{commits52}</tspan> commits/52w'
        f'  ·  ★ {r.get("stargazers_count", 0)}  ·  {ago(r["pushed_at"])}</text>'
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <linearGradient id="cbg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#0d1117"/><stop offset="1" stop-color="#0a0f16"/>
  </linearGradient>
  <linearGradient id="spk" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{THEME['phosphor']}" stop-opacity="0.35"/>
    <stop offset="1" stop-color="{THEME['phosphor']}" stop-opacity="0.02"/>
  </linearGradient>
  <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#0d1117" stop-opacity="0"/><stop offset="1" stop-color="#0d1117" stop-opacity="0.85"/>
  </linearGradient>
</defs>
<rect width="{W}" height="{H}" rx="12" fill="url(#cbg)" stroke="{THEME['border']}"/>
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
