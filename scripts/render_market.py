"""commits.sh market card — now hotlinked, nothing to render.

The README embeds https://commits.sh/api/badge?handle=maxmoneycash&style=pro
directly (dark + light), so the card is exactly as fresh as the live profile —
this fixed the "README stats don't match the site" class of bug (the old flow
committed a once-a-day snapshot SVG). Kept as a no-op so the pipeline's module
imports keep working; assets/market*.svg are no longer referenced.
"""


def render(gh, tokens):
    print("market: hotlinked from commits.sh — nothing to render")
