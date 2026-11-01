"""Keep the last published daily window when this run's daily scan failed.

The daily rows are a 35-day presentation window; all-time totals come from
the monthly scan. A timed-out daily scan falls back to an empty list, and
publishing that blanks the README's 30-day bars until the next good run
(2026-11-01 01:20Z). collect_tokens.sh calls this only after a recorded daily
scan failure, so a genuinely quiet 35 days still publishes an empty window.

Usage: carry_daily.py <published tokens.json> <built tokens.json>
"""
import json
import os
import sys


def carry_forward(previous, built):
    """(ledger, carried): the built ledger, with the previous daily rows when
    the build has none and the previous ledger does."""
    if built.get("daily") or not previous.get("daily"):
        return built, False
    # Same key, same position: only the daily rows change.
    return {**built, "daily": previous["daily"]}, True


def main(published_path, built_path):
    try:
        with open(published_path) as f:
            previous = json.load(f)
    except (OSError, ValueError):
        return 0
    with open(built_path) as f:
        built = json.load(f)
    ledger, carried = carry_forward(previous, built)
    if carried:
        tmp = f"{built_path}.carry"
        with open(tmp, "w") as f:
            json.dump(ledger, f)  # same compact form build_tokens_json prints
        os.replace(tmp, built_path)
        print(f"kept {len(ledger['daily'])} previously published daily rows")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
