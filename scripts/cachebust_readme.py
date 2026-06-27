"""Stamp a changing ?v= query on every generated image URL in README.md.

GitHub proxies README images through its camo cache (camo.githubusercontent.com),
keyed by the source URL. When an asset's bytes change but its URL does not, camo
keeps serving the stale copy — so the daily-rendered token/heatmap/market cards
can look frozen for days even though the files updated and pushed fine. Appending
a version token that changes each render gives camo a new URL, forcing a re-fetch.

Run after all README rewrites (update_readme.py / render_holdings.py) and before
the commit. Version token comes from $README_CACHE_VER (the Action passes the run
id); falls back to data/tokens.json's generated_at so local runs are deterministic.
"""
import json
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

ver = os.environ.get("README_CACHE_VER", "").strip()
if not ver:
    meta = json.load(open(ROOT / "data" / "tokens.json"))
    ver = re.sub(r"[^0-9]", "", meta.get("generated_at", "")) or "1"

text = README.read_text()
# Match generated assets (svg/png/jpg under assets/), with or without an existing
# ?v= token, and never swallow a following ) " ' or whitespace from the markdown.
pattern = re.compile(r"(assets/[^)?\"'\s]+\.(?:svg|png|jpg))(?:\?v=[0-9A-Za-z]+)?")
new_text, n = pattern.subn(rf"\1?v={ver}", text)

if new_text != text:
    README.write_text(new_text)
print(f"cachebust: stamped ?v={ver} on {n} image refs")
