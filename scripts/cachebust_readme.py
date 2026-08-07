"""Stamp a changing version query on every generated README image URL.

GitHub proxies README images through its camo cache (camo.githubusercontent.com),
keyed by the source URL. When an asset's bytes change but its URL does not, camo
keeps serving the stale copy — so generated assets and live commits.sh badges can
look frozen even though their source updated. A token that changes each hourly
render gives camo a new URL and forces a re-fetch.

Run after all README rewrites (update_readme.py / render_holdings.py) and before
the commit. Version token comes from $README_CACHE_VER (the Action passes the run
id); falls back to data/tokens.json's generated_at so local runs are deterministic.
"""
from __future__ import annotations

import json
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

ASSET_PATTERN = re.compile(
    r"(assets/[^)?\"'\s]+\.(?:svg|png|jpg))(?:\?v=[^)?\"'\s]+)?"
)
LIVE_BADGE_PATTERN = re.compile(r"https://commits\.sh/api/badge\?[^\"'\s<>]+")


def stamp_image_versions(text: str, version: str) -> tuple[str, int]:
    """Return README text with one current version on local and live images."""
    stamped, asset_count = ASSET_PATTERN.subn(rf"\1?v={version}", text)

    def stamp_live_badge(match: re.Match[str]) -> str:
        url = re.sub(r"(?:&|&amp;)v=[^&\"'\s<>]+", "", match.group(0))
        separator = "&amp;" if "&amp;" in url else "&"
        return f"{url}{separator}v={version}"

    stamped, badge_count = LIVE_BADGE_PATTERN.subn(stamp_live_badge, stamped)
    return stamped, asset_count + badge_count


def main() -> None:
    version = os.environ.get("README_CACHE_VER", "").strip()
    if not version:
        with open(ROOT / "data" / "tokens.json", encoding="utf-8") as handle:
            meta = json.load(handle)
        version = re.sub(r"[^0-9]", "", meta.get("generated_at", "")) or "1"

    text = README.read_text()
    new_text, count = stamp_image_versions(text, version)

    if new_text != text:
        README.write_text(new_text)
    print(f"cachebust: stamped version {version} on {count} image refs")


if __name__ == "__main__":
    main()
