#!/usr/bin/env python3
"""merge_token_sources.py - merge token-usage JSON from multiple machines.

The README stats pipeline runs locally on a Mac, but the user also runs a fleet
of agents on a cloud box (agent-host). This script merges the local ccusage
outputs with one or more remote machine outputs so build_tokens_json.py sees a
single combined source directory.

Usage: python3 merge_token_sources.py <output_dir> <source_dir> [<source_dir> ...]
"""

import json
import pathlib
import sys

from token_accounting import COMPONENTS, floor_total_tokens


AGENTS = ["claude", "codex", "droid", "kimi", "opencode"]
TRUE_SOURCES = ["codex-true", "kimi-true", "grok-true", "cursor", "hermes-true"]


def load(d, name):
    with open(d / name) as f:
        text = f.read()
    if not text.strip():
        raise FileNotFoundError(d / name)
    return json.loads(text)


def merge_monthly(sources):
    """Merge ccusage monthly.json sources by period."""
    by_period = {}
    for src in sources:
        for m in src.get("monthly", []):
            period = m["period"]
            if period not in by_period:
                by_period[period] = {
                    "agent": "all",
                    "period": period,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "cacheCreationTokens": 0,
                    "cacheReadTokens": 0,
                    "totalTokens": 0,
                    "totalCost": 0.0,
                    "modelsUsed": [],
                    "modelBreakdowns": [],
                    "metadata": {"agents": []},
                }
            out = by_period[period]
            for c in COMPONENTS:
                out[c] += m.get(c, 0)
            out["totalTokens"] += m.get("totalTokens", 0)
            out["totalCost"] += m.get("totalCost", 0.0)
            for model in m.get("modelsUsed", []):
                if model not in out["modelsUsed"]:
                    out["modelsUsed"].append(model)
            out["modelBreakdowns"].extend(m.get("modelBreakdowns", []))
            for agent in m.get("metadata", {}).get("agents", []):
                if agent not in out["metadata"]["agents"]:
                    out["metadata"]["agents"].append(agent)
    monthly = sorted(by_period.values(), key=lambda m: m["period"])
    for month in monthly:
        floor_total_tokens(month)
    totals = {c: sum(m.get(c, 0) for m in monthly) for c in COMPONENTS}
    totals["totalTokens"] = sum(m["totalTokens"] for m in monthly)
    totals["totalCost"] = sum(m["totalCost"] for m in monthly)
    floor_total_tokens(totals)
    return {"monthly": monthly, "totals": totals}


def merge_daily(sources):
    """Merge ccusage daily.json sources by period."""
    by_period = {}
    for src in sources:
        for d in src.get("daily", []):
            period = d["period"]
            if period not in by_period:
                by_period[period] = {
                    "agent": "all",
                    "period": period,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "cacheCreationTokens": 0,
                    "cacheReadTokens": 0,
                    "totalTokens": 0,
                    "totalCost": 0.0,
                    "modelsUsed": [],
                    "modelBreakdowns": [],
                    "metadata": {"agents": []},
                }
            out = by_period[period]
            for c in COMPONENTS:
                out[c] += d.get(c, 0)
            out["totalTokens"] += d.get("totalTokens", 0)
            out["totalCost"] += d.get("totalCost", 0.0)
            for model in d.get("modelsUsed", []):
                if model not in out["modelsUsed"]:
                    out["modelsUsed"].append(model)
            out["modelBreakdowns"].extend(d.get("modelBreakdowns", []))
            for agent in d.get("metadata", {}).get("agents", []):
                if agent not in out["metadata"]["agents"]:
                    out["metadata"]["agents"].append(agent)
    daily = sorted(by_period.values(), key=lambda d: d["period"])
    for day in daily:
        floor_total_tokens(day)
    totals = {c: sum(d.get(c, 0) for d in daily) for c in COMPONENTS}
    totals["totalTokens"] = sum(d["totalTokens"] for d in daily)
    totals["totalCost"] = sum(d["totalCost"] for d in daily)
    floor_total_tokens(totals)
    return {"daily": daily, "totals": totals}


def merge_agent(sources):
    """Merge per-agent ccusage JSON (agent-<name>.json) sources by month."""
    by_month = {}
    for src in sources:
        for m in src.get("monthly", []):
            month = m["month"]
            if month not in by_month:
                by_month[month] = {
                    "month": month,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "cacheCreationTokens": 0,
                    "cacheReadTokens": 0,
                    "totalTokens": 0,
                    "totalCost": 0.0,
                    "models": {},
                    "modelsUsed": [],
                }
            out = by_month[month]
            for c in COMPONENTS:
                out[c] += m.get(c, 0)
            out["totalTokens"] += m.get("totalTokens", 0)
            out["totalCost"] += m.get("totalCost", 0.0)
            for model, mm in (m.get("models") or {}).items():
                if model not in out["models"]:
                    out["models"][model] = {
                        "inputTokens": 0,
                        "outputTokens": 0,
                        "cacheCreationTokens": 0,
                        "cacheReadTokens": 0,
                        "totalTokens": 0,
                        "cost": 0.0,
                    }
                om = out["models"][model]
                for c in COMPONENTS + ["totalTokens", "cost"]:
                    om[c] = om.get(c, 0) + mm.get(c, 0)
                if model not in out["modelsUsed"]:
                    out["modelsUsed"].append(model)
    monthly = sorted(by_month.values(), key=lambda m: m["month"])
    for month in monthly:
        floor_total_tokens(month)
        for model in month["models"].values():
            floor_total_tokens(model)
    totals = {c: sum(m.get(c, 0) for m in monthly) for c in COMPONENTS}
    totals["totalTokens"] = sum(m["totalTokens"] for m in monthly)
    totals["totalCost"] = sum(m["totalCost"] for m in monthly)
    floor_total_tokens(totals)
    return {"monthly": monthly, "totals": totals}


def merge_true(sources):
    """Merge codex-true / kimi-true / grok-true / cursor sources by month."""
    by_month = {}
    for src in sources:
        for m in src.get("monthly", []):
            month = m["month"]
            if month not in by_month:
                by_month[month] = {
                    "month": month,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "cacheCreationTokens": 0,
                    "cacheReadTokens": 0,
                    "totalTokens": 0,
                    "totalCost": 0.0,
                    "models": {},
                }
            out = by_month[month]
            for c in COMPONENTS:
                out[c] += m.get(c, 0)
            out["totalTokens"] += m.get("totalTokens", 0)
            out["totalCost"] += m.get("totalCost", 0.0)
            for model, mm in (m.get("models") or {}).items():
                if model not in out["models"]:
                    out["models"][model] = {
                        "inputTokens": 0,
                        "outputTokens": 0,
                        "cacheCreationTokens": 0,
                        "cacheReadTokens": 0,
                        "totalTokens": 0,
                        "cost": 0.0,
                    }
                om = out["models"][model]
                for c in COMPONENTS + ["totalTokens", "cost"]:
                    om[c] += mm.get(c, 0)
    monthly = sorted(by_month.values(), key=lambda m: m["month"])
    for month in monthly:
        floor_total_tokens(month)
        for model in month["models"].values():
            floor_total_tokens(model)
    totals = {c: sum(m.get(c, 0) for m in monthly) for c in COMPONENTS}
    totals["totalTokens"] = sum(m["totalTokens"] for m in monthly)
    totals["totalCost"] = sum(m["totalCost"] for m in monthly)
    floor_total_tokens(totals)
    return {"monthly": monthly, "totals": totals}


def main():
    if len(sys.argv) < 3:
        print("usage: merge_token_sources.py <out_dir> <label>:<src_dir> [<label>:<src_dir> ...]", file=sys.stderr)
        sys.exit(1)

    out_dir = pathlib.Path(sys.argv[1])
    labels, src_dirs = [], []
    for arg in sys.argv[2:]:
        if ":" in arg:
            label, path = arg.split(":", 1)
        else:
            label, path = f"source-{len(labels) + 1}", arg
        labels.append(label)
        src_dirs.append(pathlib.Path(path))
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save per-source totals so renderers can show local vs cloud split.
    sources = []
    for label, d in zip(labels, src_dirs):
        try:
            monthly = load(d, "monthly.json")
            totals = dict(monthly.get("totals", {}))
            floor_total_tokens(totals)
        except FileNotFoundError:
            totals = {}
        sources.append({"label": label, "totals": totals})
    (out_dir / "sources.json").write_text(json.dumps(sources))

    # monthly
    monthly_sources = [load(d, "monthly.json") for d in src_dirs]
    (out_dir / "monthly.json").write_text(json.dumps(merge_monthly(monthly_sources)))

    # daily
    daily_sources = [load(d, "daily.json") for d in src_dirs]
    (out_dir / "daily.json").write_text(json.dumps(merge_daily(daily_sources)))

    # agents
    for agent in AGENTS:
        agent_sources = []
        for d in src_dirs:
            try:
                agent_sources.append(load(d, f"agent-{agent}.json"))
            except FileNotFoundError:
                pass
        if agent_sources:
            (out_dir / f"agent-{agent}.json").write_text(json.dumps(merge_agent(agent_sources)))

    # true counters / side sources
    for name in TRUE_SOURCES:
        true_sources = []
        for d in src_dirs:
            try:
                true_sources.append(load(d, f"{name}.json"))
            except FileNotFoundError:
                pass
        if true_sources:
            (out_dir / f"{name}.json").write_text(json.dumps(merge_true(true_sources)))

    print(f"merged {len(src_dirs)} source(s) into {out_dir}")


if __name__ == "__main__":
    main()
