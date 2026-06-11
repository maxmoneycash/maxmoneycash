"""Orchestrates all card renderers. Run from repo root or scripts/."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import render_city
import render_heatmaps
import render_market
import render_neofetch
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


def main():
    gh = fetch_github()
    tokens = load_tokens()
    render_neofetch.render(gh, tokens)
    ops_h = render_tokens.render(gh, tokens)
    render_receipt.render(gh, tokens, target_h=ops_h)
    render_heatmaps.render(gh, tokens)
    render_market.render(gh, tokens)
    render_city.render(gh, tokens)
    print("all cards rendered")


if __name__ == "__main__":
    main()
