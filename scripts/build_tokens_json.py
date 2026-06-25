"""Assemble data/tokens.json from ccusage outputs + true counters.

ccusage's codex adapter (v20.0.9–20.0.11) double-counts re-emitted
token_count events (~+30% for this machine's logs), so codex numbers are
replaced with scripts/codex_true_usage.py's cumulative-counter results.
ccusage's kimi adapter reads ~/.kimi/user-history (user prompts only) and
misses token metadata, so kimi numbers are replaced with
scripts/kimi_true_usage.py's wire.jsonl parsing.
Unified months/totals are then rebuilt so everything sums exactly.

Usage: python3 build_tokens_json.py <dir with monthly.json daily.json
agent-*.json codex-true.json kimi-true.json>  → corrected tokens.json on stdout.
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

    codex_rep = {m["month"]: m for m in agents_raw["codex"].get("monthly") or []}
    codex_tru = {m["month"]: m for m in codex_true["monthly"]}
    kimi_rep = {m["month"]: m for m in agents_raw["kimi"].get("monthly") or []}
    kimi_tru = {m["month"]: m for m in kimi_true["monthly"]}

    def rep_models(rep):
        # per-agent schema: models is a dict keyed by model name
        return set((rep.get("models") or {}).keys()) | set(rep.get("modelsUsed") or [])

    def rep_total(rep):
        return rep.get("totalTokens") or sum(rep.get(c, 0) for c in COMPONENTS)

    codex_cost = 0.0
    monthly = []
    for m in unified["monthly"]:
        m = dict(m)
        month = m["period"]

        # Correct codex (double-counted by ccusage).
        rep = codex_rep.get(month)
        tru = codex_tru.get(month)
        factor = 1.0
        if rep and rep_total(rep):
            tru_tot = tru["totalTokens"] if tru else 0
            factor = tru_tot / rep_total(rep)
            for c in COMPONENTS:
                m[c] = m.get(c, 0) - rep.get(c, 0) + (tru.get(c, 0) if tru else 0)
            m["totalTokens"] = m["totalTokens"] - rep_total(rep) + tru_tot

        # Correct kimi (ccusage reads user-history, missing token metadata).
        krep = kimi_rep.get(month)
        ktru = kimi_tru.get(month)
        if krep and rep_total(krep):
            ktru_tot = ktru["totalTokens"] if ktru else 0
            for c in COMPONENTS:
                m[c] = m.get(c, 0) - krep.get(c, 0) + (ktru.get(c, 0) if ktru else 0)
            m["totalTokens"] = m["totalTokens"] - rep_total(krep) + ktru_tot

        # Rescale codex-model breakdowns (cost is an estimate, pro-rated by
        # the corrected token volume) and rebuild the month's cost.
        codex_models = rep_models(rep or {})
        breakdowns = []
        total_cost = 0.0
        for b in m.get("modelBreakdowns", []):
            b = dict(b)
            if b["modelName"] in codex_models and factor != 1.0:
                for c in COMPONENTS + ["cost"]:
                    if c in b and isinstance(b[c], (int, float)):
                        b[c] = b[c] * factor
                for c in COMPONENTS:
                    b[c] = int(b[c])
                codex_cost += b.get("cost", 0)
            elif b["modelName"] in codex_models:
                codex_cost += b.get("cost", 0)
            total_cost += b.get("cost", 0)
            breakdowns.append(b)
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
        "totals": {**codex_true["totals"], "totalCost": codex_cost},
        "monthly": [
            {**m, "modelsUsed": models_used.get(m["month"], [])}
            for m in codex_true["monthly"]
        ],
    }
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

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "totals": totals,
        "monthly": monthly,
        "daily": daily["daily"],
        "agents": agents,
        "corrections": {
            "codexReemitBugAdjusted": True,
            "codexReportedTotal": agents_raw["codex"].get("totals", {}).get("totalTokens"),
            "codexTrueTotal": codex_true["totals"]["totalTokens"],
            "kimiWireAdjusted": True,
            "kimiReportedTotal": agents_raw["kimi"].get("totals", {}).get("totalTokens"),
            "kimiTrueTotal": kimi_true["totals"].get("totalTokens"),
            "note": (
                "codex counted from cumulative total_token_usage deltas; "
                "ccusage <=20.0.11 double-counts re-emitted token_count events. "
                "kimi counted from ~/.kimi/sessions/**/wire.jsonl StatusUpdate "
                "token_usage; ccusage reads user-history and undercounts. "
                "codex model costs pro-rated by corrected volume. daily[] series "
                "left as reported (relative shape only)."
            ),
        },
    }
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
