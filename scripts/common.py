"""Shared helpers for the README card renderers."""
import json
import os
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
LOGIN = "maxmoneycash"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""

# One palette for every card so the profile reads as a single rice.
THEME = {
    "bg": "#0d1117",
    "bg2": "#10151d",
    "panel": "#161b22",
    "border": "#30363d",
    "fg": "#c9d1d9",
    "muted": "#8b949e",
    "green": "#39d353",
    "phosphor": "#53fca1",
    "amber": "#ffb454",
    "key": "#ffa657",
    "value": "#a5d6ff",
}

# Classic six-stripe Apple logo colors (top to bottom).
APPLE_STRIPES = ["#61bb46", "#fdb827", "#f5821f", "#e03a3e", "#963d97", "#009ddc"]

AGENT_COLORS = {
    "claude": "#d97757",
    "codex": "#19c37d",
    "droid": "#58a6ff",
    "kimi": "#a371f7",
    "opencode": "#f2cc60",
    "cursor": "#e3e9f0",
    "grok": "#1d9bf0",
}

AGENT_LABELS = {
    "claude": "CLAUDE CODE",
    "codex": "CODEX",
    "droid": "DROID",
    "kimi": "KIMI CODE",
    "opencode": "OPENCODE",
    "cursor": "CURSOR",
    "grok": "GROK BUILD",
}


def esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def compact(n):
    n = float(n)
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            v = n / div
            return f"{v:.2f}{suffix}" if v < 10 else f"{v:.1f}{suffix}"
    return f"{n:.0f}"


def money(x, cents=False):
    return f"${x:,.2f}" if cents else f"${x:,.0f}"


def load_tokens():
    with open(ROOT / "data" / "tokens.json") as f:
        return json.load(f)


def _request(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("User-Agent", LOGIN)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def gh_api(path):
    return _request(f"https://api.github.com{path}")


def gh_graphql(query, variables):
    payload = json.dumps({"query": query, "variables": variables}).encode()
    out = _request(
        "https://api.github.com/graphql",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    if "errors" in out:
        raise RuntimeError(out["errors"])
    return out["data"]


def write_svg(name, svg):
    ASSETS.mkdir(exist_ok=True)
    path = ASSETS / name
    path.write_text(svg)
    print(f"wrote {path.relative_to(ROOT)} ({len(svg)} bytes)")
