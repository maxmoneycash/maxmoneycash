"""Holdings showcase: each repo as a card with a live app screenshot banner,
a 52-week commit sparkline, $ticker, language pill, and stats.

Screenshots live in assets/shots/<repo>.jpg (captured by the workflow's
Playwright step, or hand-supplied). A repo with no shot renders banner-less.
Commit activity is the GitHub REST commit_activity series (retries on 202).
"""
import base64
import datetime
import json
import pathlib

from common import LOGIN, THEME, esc, gh_api, write_svg

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHOTS = ROOT / "assets" / "shots"
MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"

LANG_COLORS = {
    "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Python": "#3572A5",
    "Move": "#4a90e2", "Rust": "#dea584", "HTML": "#e34c26", "Solidity": "#AA6746",
    "Svelte": "#ff3e00", "C++": "#f34b7d", "Go": "#00ADD8",
}

# Curated showcase loaded from scripts/showcase.json (shared with the
# screenshot step); each entry: {repo, url} — empty url = banner-less card.
SHOWCASE = [
    (h["repo"], h.get("url", ""))
    for h in json.loads((ROOT / "scripts" / "showcase.json").read_text())["holdings"]
]

W = 460


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


def weekly_commits(repo):
    for _ in range(3):
        try:
            data = gh_api(f"/repos/{LOGIN}/{repo}/stats/commit_activity")
        except Exception:
            data = None
        if isinstance(data, list) and data:
            return [w.get("total", 0) for w in data[-52:]]
    return [0] * 52


def render_card(repo, url):
    t = THEME
    try:
        r = gh_api(f"/repos/{LOGIN}/{repo}")
    except Exception:
        return None
    lang = (r.get("language") or "—")
    lang_color = LANG_COLORS.get(lang, "#8b949e")
    desc = (r.get("description") or "").strip()
    weekly = weekly_commits(repo)
    commits52 = sum(weekly)

    shot = SHOTS / f"{repo}.jpg"
    has_shot = shot.exists()
    banner_h = 150 if has_shot else 0
    H = banner_h + 168

    parts = []
    # ---- banner (embedded live screenshot) ----
    if has_shot:
        b64 = base64.b64encode(shot.read_bytes()).decode()
        parts.append(
            f'<clipPath id="bclip"><rect x="0" y="0" width="{W}" height="{banner_h}" rx="12"/></clipPath>'
            f'<image href="data:image/jpeg;base64,{b64}" x="0" y="0" width="{W}" height="{banner_h}" '
            f'preserveAspectRatio="xMidYMid slice" clip-path="url(#bclip)"/>'
            f'<rect x="0" y="{banner_h - 40}" width="{W}" height="40" fill="url(#fade)"/>'
            f'<rect x="0" y="0" width="{W}" height="{banner_h}" rx="12" fill="none" stroke="{t["border"]}"/>'
            f'<text x="{W - 12}" y="{banner_h - 12}" text-anchor="end" font-size="9" '
            f'fill="#cdd9e5" opacity="0.85">{esc(url.replace("https://", ""))} ↗</text>'
        )
    py = banner_h + 30

    # ---- name + ticker ----
    ticker = "$" + "".join(c for c in repo.upper() if c.isalnum())[:6]
    parts.append(
        f'<text x="20" y="{py}" font-size="17" font-weight="700" fill="{t["phosphor"]}">{esc(repo)}</text>'
        f'<text x="{20 + len(repo) * 10.5 + 12}" y="{py}" font-size="10" fill="{t["muted"]}">{ticker}</text>'
        f'<g><rect x="{W - 20 - (len(lang) * 7 + 26)}" y="{py - 15}" width="{len(lang) * 7 + 26}" height="20" rx="10" '
        f'fill="{t["panel"]}" stroke="{lang_color}" stroke-opacity="0.6"/>'
        f'<circle cx="{W - 20 - (len(lang) * 7 + 26) + 13}" cy="{py - 5}" r="4" fill="{lang_color}"/>'
        f'<text x="{W - 26}" y="{py - 1}" text-anchor="end" font-size="10" fill="{t["fg"]}">{esc(lang)}</text></g>'
    )
    # ---- description ----
    if desc:
        if len(desc) > 64:
            desc = desc[:61] + "..."
        parts.append(f'<text x="20" y="{py + 22}" font-size="11.5" fill="{t["fg"]}">{esc(desc)}</text>')

    # ---- sparkline (52w) ----
    sx, sy, sw, sh = 20, py + 38, W - 40, 38
    wmax = max(max(weekly), 1)
    pts = " ".join(f"{sx + i * sw / 51:.1f},{sy + sh - sh * v / wmax:.1f}" for i, v in enumerate(weekly))
    parts.append(
        f'<polygon points="{sx},{sy + sh} {pts} {sx + sw},{sy + sh}" fill="url(#spk)"/>'
        f'<polyline points="{pts}" fill="none" stroke="{t["phosphor"]}" stroke-width="1.4"/>'
        f'<text x="{sx}" y="{sy + sh + 15}" font-size="9" fill="{t["muted"]}">52-WEEK COMMIT FLOW</text>'
    )
    # ---- stats ----
    parts.append(
        f'<text x="{W - 20}" y="{sy + sh + 15}" text-anchor="end" font-size="11" fill="{t["fg"]}">'
        f'<tspan fill="{t["phosphor"]}" font-weight="700">{commits52}</tspan> commits/52w'
        f'  ·  ★ {r.get("stargazers_count", 0)}'
        f'  ·  {ago(r["pushed_at"])}</text>'
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" font-family="{MONO}">
<defs>
  <linearGradient id="cbg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#0d1117"/><stop offset="1" stop-color="#0a0f16"/>
  </linearGradient>
  <linearGradient id="spk" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{THEME['mint'] if 'mint' in THEME else THEME['phosphor']}" stop-opacity="0.35"/>
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


def render(gh=None, tokens=None):
    done = []
    for repo, url in SHOWCASE:
        if render_card(repo, url):
            done.append(repo)
    print(f"rendered {len(done)} holding cards")
    return done


if __name__ == "__main__":
    render()
