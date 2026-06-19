"""Orchestrates all card renderers. Run from repo root or scripts/."""
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import render_heatmaps
import render_market
import render_neofetch
import render_wrapped
import render_receipt
import render_tokens
from common import LOGIN, gh_api, load_tokens


def fetch_github():
    user = gh_api(f"/users/{LOGIN}")
    stars, langs, page = 0, {}, 1
    while True:
        repos = gh_api(f"/users/{LOGIN}/repos?per_page=100&page={page}")
        stars += sum(r["stargazers_count"] for r in repos)
        for r in repos:
            if r["language"] and not r["fork"]:
                langs[r["language"]] = langs.get(r["language"], 0) + 1
        if len(repos) < 100:
            break
        page += 1
    return {"user": user, "stars": stars, "langs": langs}


MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace"


def _inner(svg_text):
    m = re.match(
        r'<svg[^>]*viewBox="0 0 (\d+) (\d+)"[^>]*>(.*)</svg>\s*$', svg_text, re.S
    )
    return int(m.group(1)), int(m.group(2)), m.group(3)


def build_token_combos():
    """Combine receipt + token-ops into one row SVG (desktop, width 100%)
    and one stacked SVG (mobile, via a <picture> media query)."""
    from common import ASSETS, write_svg

    rw, rh, rb = _inner((ASSETS / "receipt.svg").read_text())
    ow, oh, ob = _inner((ASSETS / "token-ops.svg").read_text())
    gap = 28
    row = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {rw + ow + gap} {max(rh, oh)}" '
        f'width="{rw + ow + gap}" font-family="{MONO}">'
        f"<g>{rb}</g>"
        f'<g transform="translate({rw + gap},0)">{ob}</g></svg>'
    )
    write_svg("tokens-row.svg", row)
    stack = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {max(rw, ow)} {rh + oh + gap}" '
        f'width="{max(rw, ow)}" font-family="{MONO}">'
        f"<g>{rb}</g>"
        f'<g transform="translate(0,{rh + gap})">{ob}</g></svg>'
    )
    write_svg("tokens-stack.svg", stack)


def main():
    gh = fetch_github()
    tokens = load_tokens()
    render_neofetch.render(gh, tokens)
    receipt_h = render_receipt.natural_height(gh, tokens)
    ops_h = render_tokens.render(gh, tokens, target_h=receipt_h)
    render_receipt.render(gh, tokens, target_h=ops_h)
    build_token_combos()
    render_heatmaps.render(gh, tokens)
    render_market.render(gh, tokens)
    render_wrapped.render(gh, tokens)
    print("all cards rendered")


if __name__ == "__main__":
    main()
