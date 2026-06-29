"""Commit-markets card for the README (dark + light).

Instead of re-implementing the chart in Python (which always drifts from the live
site), pull the app's OWN badge SVG — the canonical `pro` style from
commit-markets/web/src/lib/badges (same candle renderer, color tokens, and stats
as commit-markets.vercel.app). We fetch BOTH themes and commit assets/market.svg
(dark) + assets/market-light.svg (light); the README embeds them via <picture>
with prefers-color-scheme so GitHub serves the white card in light mode. Each is
Camo-cache-busted by update_readme's ?v= stamp, and a momentary app outage can
never blank the README (we keep the last good card per theme).
"""
import urllib.request

from common import LOGIN, write_svg

STYLE = "pro"


def _badge_url(theme):
    return (
        f"https://commits.sh/api/badge"
        f"?handle={LOGIN}&style={STYLE}&theme={theme}"
    )


def _fetch(theme, out_name):
    try:
        req = urllib.request.Request(_badge_url(theme), headers={"User-Agent": LOGIN})
        with urllib.request.urlopen(req, timeout=30) as resp:
            svg = resp.read().decode("utf-8")
    except Exception as e:  # network blip, 5xx, timeout — keep last good card
        print(f"market: {theme} badge fetch failed ({e}); keeping existing {out_name}")
        return
    # Guard against an error/fallback card overwriting the real one: the badge
    # endpoint returns a tiny "temporarily unavailable" SVG on failure (<800 B,
    # no candle <rect> bars). Only commit a card that actually drew candles.
    if not svg.lstrip().startswith("<svg") or "<rect" not in svg or len(svg) < 2000:
        print(f"market: {theme} badge looked like a fallback ({len(svg)} B); keeping existing")
        return
    write_svg(out_name, svg)


def render(gh, tokens):
    _fetch("dark", "market.svg")
    _fetch("light", "market-light.svg")
