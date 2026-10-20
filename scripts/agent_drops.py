"""Name every agent whose all-time total fell between two ledgers.

collect_tokens.sh refuses to publish such a ledger. A scan that times out
falls back to empty JSON, which can erase one agent while the overall total
still grows: on 2026-10-20 agent-codex and codex-true timed out under load
and data/tokens.json published Codex at 22.69B instead of 39.85B.

Usage: agent_drops.py OLD_LEDGER NEW_LEDGER  (prints "" when nothing fell)
"""
import json
import sys

# Rounding and pricing noise only; a lost source moves far more than this.
TOLERANCE = 0.005


def agent_totals(ledger):
    agents = (ledger or {}).get("agents") or {}
    return {name: ((agent or {}).get("totals") or {}).get("totalTokens") or 0
            for name, agent in agents.items()}


def drops(old, new, tolerance=TOLERANCE):
    before, after = agent_totals(old), agent_totals(new)
    return [f"{name} {before[name]}->{after.get(name, 0)}"
            for name in sorted(before)
            if before[name] > 0 and after.get(name, 0) < before[name] * (1 - tolerance)]


def main(argv):
    try:
        with open(argv[1]) as handle:
            old = json.load(handle)
    except (OSError, ValueError):
        old = {}
    with open(argv[2]) as handle:
        new = json.load(handle)
    print("; ".join(drops(old, new)))


if __name__ == "__main__":
    main(sys.argv)
