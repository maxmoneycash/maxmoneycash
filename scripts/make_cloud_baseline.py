#!/usr/bin/env python3
"""make_cloud_baseline.py - freeze lost cloud usage as a permanent baseline.

On 2026-07-05 the DigitalOcean agent box was rebuilt (as hermes-agent) and its
~/.claude session logs — the raw source of ~16.4B tokens of fleet usage — were
deleted. ccusage recounts from raw logs on every run, so that usage would
otherwise vanish from tokens.json forever (the collector's monotonic guard has
been correctly refusing to publish the regression since then).

This one-off computes that lost cloud contribution by subtraction:

    baseline = last-good tokens.json (built while the old box was alive)
             - a fresh LOCAL-ONLY build (this Mac's logs are immutable history)

Month-by-month, per-agent, per-model, clipped at zero. Exact for every month
the local side hasn't grown since the last good build (all months before the
current one); the current month's cloud slice is clipped by local growth.

Usage:
    python3 make_cloud_baseline.py <old_tokens.json> <local_only_tokens.json> \
        > data/cloud-baseline.json

build_tokens_json.py adds data/cloud-baseline.json back into every build.
"""
import json
import sys

COMPONENTS = ["inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens"]
NUMS = COMPONENTS + ["totalTokens", "totalCost"]


def agg_models(breakdowns):
    """Aggregate a modelBreakdowns list into one row per model name."""
    out = {}
    for b in breakdowns or []:
        name = b.get("modelName", "unknown")
        row = out.setdefault(name, {c: 0 for c in COMPONENTS} | {"cost": 0.0})
        for c in COMPONENTS + ["cost"]:
            row[c] += b.get(c, 0)
    return out


def sub_models(old, new):
    """Per-model subtraction of aggregated model dicts, clipped at zero."""
    res = {}
    for name, o in old.items():
        n = new.get(name, {})
        row = {c: max(0, o.get(c, 0) - n.get(c, 0)) for c in COMPONENTS}
        row["cost"] = max(0.0, o.get("cost", 0) - n.get("cost", 0))
        row["totalTokens"] = sum(row[c] for c in COMPONENTS)
        if row["totalTokens"] > 0 or row["cost"] > 0:
            res[name] = row
    return res


def sub_series(old_rows, new_rows, key):
    """Subtract two period-keyed series (monthly by 'period', agent monthly by
    'month', daily by 'period'), clipped at zero. Keeps old metadata."""
    new_by = {r[key]: r for r in new_rows or []}
    out = []
    for o in old_rows or []:
        n = new_by.get(o[key], {})
        row = {key: o[key]}
        for c in NUMS:
            row[c] = max(0, o.get(c, 0) - n.get(c, 0))
        if row["totalTokens"] <= 0:
            continue
        if "modelBreakdowns" in o:
            models = sub_models(agg_models(o.get("modelBreakdowns")),
                                agg_models(n.get("modelBreakdowns")))
            row["modelBreakdowns"] = [
                {"modelName": m, **{c: v[c] for c in COMPONENTS}, "cost": v["cost"]}
                for m, v in sorted(models.items())
            ]
            row["modelsUsed"] = sorted(models.keys())
        if "models" in o:  # per-agent schema: dict keyed by model name
            row["models"] = sub_models(
                {m: {**v, "cost": v.get("cost", 0)} for m, v in (o.get("models") or {}).items()},
                {m: {**v, "cost": v.get("cost", 0)} for m, v in (n.get("models") or {}).items()},
            )
            row["modelsUsed"] = sorted(row["models"].keys())
        if o.get("metadata"):
            row["metadata"] = o["metadata"]
        row["agent"] = o.get("agent", "all")
        out.append(row)
    return out


def totals_of(rows):
    t = {c: sum(r.get(c, 0) for r in rows) for c in COMPONENTS}
    t["totalTokens"] = sum(r.get("totalTokens", 0) for r in rows)
    t["totalCost"] = sum(r.get("totalCost", 0.0) for r in rows)
    return t


def main():
    old = json.load(open(sys.argv[1]))
    new = json.load(open(sys.argv[2]))

    monthly = sub_series(old["monthly"], new["monthly"], "period")
    daily = sub_series(old.get("daily") or [], new.get("daily") or [], "period")

    agents = {}
    for name, o in (old.get("agents") or {}).items():
        n = (new.get("agents") or {}).get(name) or {}
        rows = sub_series(o.get("monthly") or [], n.get("monthly") or [], "month")
        if rows:
            agents[name] = {"totals": totals_of(rows), "monthly": rows}

    out = {
        "note": (
            "Frozen contribution of the pre-2026-07-05 cloud agent box, whose "
            "session logs were destroyed in the hermes-agent rebuild. Computed "
            "as last-good tokens.json minus a local-only rebuild. Added back "
            "into every build by build_tokens_json.py. Do not delete: this "
            "usage is unrecoverable from raw logs."
        ),
        "as_of": old.get("generated_at"),
        "totals": totals_of(monthly),
        "monthly": monthly,
        "daily": daily,
        "agents": agents,
    }
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
