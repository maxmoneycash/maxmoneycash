"""Assemble data/tokens.json from ccusage outputs + true counters.

Codex numbers come straight from ccusage (the raw session logs are treated as
authoritative). Kimi is corrected because ccusage reads ~/.kimi/user-history
(user prompts only) and misses token metadata; we replace it with
scripts/kimi_true_usage.py's wire.jsonl parsing.
Unified months/totals are then rebuilt so everything sums exactly.

Usage: python3 build_tokens_json.py <dir with monthly.json daily.json
agent-*.json codex-true.json kimi-true.json> [baseline.json]  → tokens.json
on stdout.

The optional baseline (data/cloud-baseline.json, made by make_cloud_baseline.py)
is the frozen contribution of the old cloud box whose raw logs were destroyed
in the 2026-07-05 rebuild; it is added on top of everything recounted from
live logs.
"""
import datetime
import json
import pathlib
import sys

COMPONENTS = ["inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens"]


def load(d, name):
    with open(d / name) as f:
        text = f.read()
    if not text.strip():
        raise FileNotFoundError(d / name)
    return json.loads(text)


def main():
    d = pathlib.Path(sys.argv[1])
    unified = load(d, "monthly.json")
    daily = load(d, "daily.json")
    agents_raw = {
        a: load(d, f"agent-{a}.json")
        for a in ("claude", "codex", "droid", "kimi", "opencode")
    }
    codex_true = load(d, "codex-true.json")
    try:
        cursor = load(d, "cursor.json")
    except FileNotFoundError:
        cursor = {"totals": {}, "monthly": []}
    try:
        grok = load(d, "grok-true.json")
    except FileNotFoundError:
        grok = {"totals": {}, "monthly": []}
    try:
        kimi_true = load(d, "kimi-true.json")
    except FileNotFoundError:
        kimi_true = {"totals": {}, "monthly": []}
    try:
        sources = load(d, "sources.json")
    except FileNotFoundError:
        sources = []

    kimi_rep = {m["month"]: m for m in agents_raw["kimi"].get("monthly") or []}
    kimi_tru = {m["month"]: m for m in kimi_true["monthly"]}

    def rep_models(rep):
        # per-agent schema: models is a dict keyed by model name
        return set((rep.get("models") or {}).keys()) | set(rep.get("modelsUsed") or [])

    def rep_total(rep):
        return rep.get("totalTokens") or sum(rep.get(c, 0) for c in COMPONENTS)

    monthly = []
    for m in unified["monthly"]:
        m = dict(m)
        month = m["period"]

        # Correct kimi (ccusage reads user-history, missing token metadata).
        krep = kimi_rep.get(month)
        ktru = kimi_tru.get(month)
        if krep and rep_total(krep):
            ktru_tot = ktru["totalTokens"] if ktru else 0
            for c in COMPONENTS:
                m[c] = m.get(c, 0) - krep.get(c, 0) + (ktru.get(c, 0) if ktru else 0)
            m["totalTokens"] = m["totalTokens"] - rep_total(krep) + ktru_tot

        # Rebuild the month's cost from the (possibly corrected) model rows.
        breakdowns = []
        total_cost = 0.0
        for b in m.get("modelBreakdowns", []):
            total_cost += b.get("cost", 0)
            breakdowns.append(dict(b))
        m["modelBreakdowns"] = breakdowns
        m["totalCost"] = total_cost
        monthly.append(m)

    # Merge a token-accounted side source (cursor dashboard, grok logs) into the
    # unified monthly series — each contributes its own components + model rows.
    by_period = {m["period"]: m for m in monthly}

    def merge_source(src, label):
        for cm in src.get("monthly") or []:
            m = by_period.get(cm["month"])
            if m is None:
                m = {
                    "period": cm["month"], "agent": "all",
                    "inputTokens": 0, "outputTokens": 0, "cacheCreationTokens": 0,
                    "cacheReadTokens": 0, "totalTokens": 0, "totalCost": 0.0,
                    "modelsUsed": [], "modelBreakdowns": [],
                    "metadata": {"agents": [label]},
                }
                by_period[cm["month"]] = m
                monthly.append(m)
            else:
                m.setdefault("metadata", {}).setdefault("agents", []).append(label)
            for c in COMPONENTS:
                m[c] = m.get(c, 0) + cm.get(c, 0)
            m["totalTokens"] += cm["totalTokens"]
            m["totalCost"] += cm.get("totalCost", 0)
            for model, mm in (cm.get("models") or {}).items():
                m["modelBreakdowns"].append({
                    "modelName": model,
                    "inputTokens": mm.get("inputTokens", 0),
                    "outputTokens": mm.get("outputTokens", 0),
                    "cacheCreationTokens": mm.get("cacheCreationTokens", 0),
                    "cacheReadTokens": mm.get("cacheReadTokens", 0),
                    "cost": mm.get("cost", 0),
                })
                if model not in m.get("modelsUsed", []):
                    m.setdefault("modelsUsed", []).append(model)

    merge_source(cursor, "cursor")  # token accounting from 2025-07 (earlier was request-based)
    merge_source(grok, "grok")

    # --- frozen cloud baseline: usage from the old agent box whose logs were
    #     destroyed in the 2026-07-05 hermes rebuild. Everything above is
    #     recounted from raw logs on every run; this slice has no raw logs
    #     left, so it is added back verbatim. ---
    baseline = None
    if len(sys.argv) > 2:
        try:
            baseline = json.load(open(sys.argv[2]))
        except FileNotFoundError:
            baseline = None
    if baseline:
        for bm in baseline.get("monthly", []):
            m = by_period.get(bm["period"])
            if m is None:
                m = {
                    "period": bm["period"], "agent": "all",
                    "inputTokens": 0, "outputTokens": 0, "cacheCreationTokens": 0,
                    "cacheReadTokens": 0, "totalTokens": 0, "totalCost": 0.0,
                    "modelsUsed": [], "modelBreakdowns": [],
                    "metadata": {"agents": []},
                }
                by_period[bm["period"]] = m
                monthly.append(m)
            for c in COMPONENTS + ["totalTokens", "totalCost"]:
                m[c] = m.get(c, 0) + bm.get(c, 0)
            m["modelBreakdowns"].extend(bm.get("modelBreakdowns", []))
            for model in bm.get("modelsUsed", []):
                if model not in m.get("modelsUsed", []):
                    m.setdefault("modelsUsed", []).append(model)
            for agent in (bm.get("metadata") or {}).get("agents", []):
                agents_list = m.setdefault("metadata", {}).setdefault("agents", [])
                if agent not in agents_list:
                    agents_list.append(agent)

        by_day = {dd["period"]: dd for dd in daily["daily"]}
        for bd in baseline.get("daily", []):
            dd = by_day.get(bd["period"])
            if dd is None:
                continue  # outside the live 35-day window; totals come from monthly
            for c in COMPONENTS + ["totalTokens", "totalCost"]:
                dd[c] = dd.get(c, 0) + bd.get(c, 0)

    monthly.sort(key=lambda m: m["period"])

    totals = {c: sum(m.get(c, 0) for m in monthly) for c in COMPONENTS}
    totals["totalTokens"] = sum(m["totalTokens"] for m in monthly)
    totals["totalCost"] = sum(m["totalCost"] for m in monthly)

    agents = {}
    for name, raw in agents_raw.items():
        agents[name] = {"totals": raw.get("totals") or {}, "monthly": raw.get("monthly") or []}
    # Replace codex with the true counts; keep ccusage's model lists.
    models_used = {
        m["month"]: sorted(rep_models(m)) for m in agents["codex"]["monthly"]
    }
    agents["codex"] = {
        "totals": agents_raw["codex"].get("totals") or {},
        "monthly": agents_raw["codex"].get("monthly") or [],
    }
    # models_used was kept for codex correction display; no longer needed but
    # harmless to leave empty.
    models_used = {}
    agents["cursor"] = {
        "totals": cursor.get("totals") or {},
        "monthly": cursor.get("monthly") or [],
    }
    agents["grok"] = {
        "totals": grok.get("totals") or {},
        "monthly": grok.get("monthly") or [],
    }
    agents["kimi"] = {
        "totals": kimi_true.get("totals") or {},
        "monthly": kimi_true.get("monthly") or [],
    }

    if baseline:
        for name, b in (baseline.get("agents") or {}).items():
            a = agents.setdefault(name, {"totals": {}, "monthly": []})
            at = a["totals"]
            for c in COMPONENTS + ["totalTokens", "totalCost"]:
                at[c] = at.get(c, 0) + b.get("totals", {}).get(c, 0)
            by_month = {m["month"]: m for m in a["monthly"]}
            for bm in b.get("monthly", []):
                m = by_month.get(bm["month"])
                if m is None:
                    a["monthly"].append(dict(bm))
                    continue
                for c in COMPONENTS + ["totalTokens", "totalCost"]:
                    m[c] = m.get(c, 0) + bm.get(c, 0)
                models = m.setdefault("models", {})
                for model, mm in (bm.get("models") or {}).items():
                    om = models.setdefault(model, {})
                    for c in COMPONENTS + ["totalTokens", "cost"]:
                        om[c] = om.get(c, 0) + mm.get(c, 0)
                    if model not in m.get("modelsUsed", []):
                        m.setdefault("modelsUsed", []).append(model)
            a["monthly"].sort(key=lambda m: m["month"])
        sources = list(sources) + [{
            "label": "cloud-baseline",
            "totals": baseline.get("totals", {}),
        }]

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "totals": totals,
        "monthly": monthly,
        "daily": daily["daily"],
        "agents": agents,
        "sources": sources,
        "corrections": {
            "kimiWireAdjusted": True,
            "kimiReportedTotal": agents_raw["kimi"].get("totals", {}).get("totalTokens"),
            "kimiTrueTotal": kimi_true["totals"].get("totalTokens"),
            "note": (
                "codex numbers come straight from ccusage. "
                "kimi counted from ~/.kimi/sessions/**/wire.jsonl StatusUpdate "
                "token_usage; ccusage reads user-history and undercounts. "
                "daily[] series left as reported (relative shape only)."
            ),
        },
    }
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
