#!/usr/bin/env python3
"""Hermes gateway usage (the cloud swarm's 8th agent) → tokens.json schema.

The hermes-agent box runs the peat-ui swarm through the Hermes gateway
(OpenAI Codex OAuth), which does NOT write ~/.claude or ~/.codex session
logs — its token accounting lives only in /root/.hermes/**/state.db
`sessions` rows (per-session input/output/cache/reasoning counters,
started_at as epoch seconds). ccusage can't see any of it.

collect_cloud_tokens.sh dumps those rows to hermes-sessions.json and this
script folds them into data/hermes-cache.json keyed by profile:session-id,
keeping the LARGEST value seen per session (session counters only grow).
The committed cache is the durable record: the 2026-07-05 box rebuild
destroyed 16.4B tokens of raw logs, so cloud usage is never again trusted
to live only on the box. Pruned sessions and even a full box wipe cannot
shrink the cache.

Field mapping → tokens.json schema:
  inputTokens         = input_tokens
  outputTokens        = output_tokens + reasoning_tokens
  cacheReadTokens     = cache_read_tokens
  cacheCreationTokens = cache_write_tokens
Cost = 0 (subscription OAuth, no per-token price).

Usage:
  hermes_true_usage.py <hermes-sessions.json>   fold dump into cache, emit monthly
  hermes_true_usage.py                          emit from cache alone (box offline)

Outputs {totals, monthly:[...]} (cursor/codex schema) to stdout.
"""
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "hermes-cache.json"
COMPONENTS = ["inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens"]


def load_cache():
    try:
        c = json.loads(CACHE.read_text())
        if isinstance(c.get("sessions"), dict):
            return c
    except Exception:
        pass
    return {"sessions": {}}


def month_of(started_at):
    try:
        return datetime.datetime.fromtimestamp(
            float(started_at), datetime.timezone.utc
        ).strftime("%Y-%m")
    except Exception:
        return "unknown"


def main():
    cache = load_cache()
    sessions = cache["sessions"]

    if len(sys.argv) > 1:
        dump = json.loads(pathlib.Path(sys.argv[1]).read_text())
        for row in dump:
            key = f"{row.get('profile', 'main')}:{row['id']}"
            entry = {
                "month": month_of(row.get("started_at")),
                "model": row.get("model") or "unknown",
                "inputTokens": row.get("input_tokens") or 0,
                "outputTokens": (row.get("output_tokens") or 0)
                + (row.get("reasoning_tokens") or 0),
                "cacheCreationTokens": row.get("cache_write_tokens") or 0,
                "cacheReadTokens": row.get("cache_read_tokens") or 0,
            }
            if sum(entry[c] for c in COMPONENTS) == 0:
                continue
            old = sessions.get(key)
            # session counters only grow; keep the largest snapshot ever seen
            if old is None or sum(entry[c] for c in COMPONENTS) >= sum(
                old.get(c, 0) for c in COMPONENTS
            ):
                sessions[key] = entry
        CACHE.write_text(json.dumps(cache, sort_keys=True))

    monthly = {}
    for entry in sessions.values():
        m = monthly.setdefault(
            entry["month"],
            {c: 0 for c in COMPONENTS} | {"totalTokens": 0, "totalCost": 0.0, "models": {}},
        )
        model = entry.get("model") or "unknown"
        mm = m["models"].setdefault(
            model, {c: 0 for c in COMPONENTS} | {"totalTokens": 0, "cost": 0.0}
        )
        for c in COMPONENTS:
            v = entry.get(c, 0)
            m[c] += v
            mm[c] += v
            m["totalTokens"] += v
            mm["totalTokens"] += v

    out_monthly = [{"month": k, **v} for k, v in sorted(monthly.items())]
    totals = {c: sum(m[c] for m in out_monthly) for c in COMPONENTS}
    totals["totalTokens"] = sum(m["totalTokens"] for m in out_monthly)
    totals["totalCost"] = 0.0
    generated = (datetime.datetime.now(datetime.timezone.utc)
                 .isoformat(timespec="seconds").replace("+00:00", "Z"))
    json.dump({"totals": totals, "monthly": out_monthly, "generated_at": generated},
              sys.stdout)


if __name__ == "__main__":
    main()
