"""Assemble data/tokens.json from ccusage outputs + true counters.

Codex is corrected with cumulative token deltas because ccusage counts repeated
token_count events. Kimi is corrected because ccusage reads ~/.kimi/user-history
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
import copy
import json
import pathlib
import sys

from token_accounting import COMPONENTS, floor_total_tokens


PLACEHOLDER_MODELS = {"auto", "default", "unknown"}
MODEL_ALIASES = {
    "gpt-5-3-codex": "gpt-5.3-codex",
    "gpt-5-codex-high": "gpt-5-codex",
    "gpt-5.1-codex-high": "gpt-5.1-codex",
}
ACCOUNTING_REVISION = "headline-component-floor-v2"


def load(d, name):
    with open(d / name) as f:
        text = f.read()
    if not text.strip():
        raise FileNotFoundError(d / name)
    return json.loads(text)


def model_total(row):
    return sum(row.get(c, 0) or 0 for c in COMPONENTS)


def canonical_model(name):
    if not isinstance(name, str):
        return None
    normalized = name.strip().lower()
    if not normalized or normalized in PLACEHOLDER_MODELS:
        return None
    return MODEL_ALIASES.get(normalized, normalized)


def aggregate_breakdowns(rows):
    """Canonicalize aliases, drop placeholders, and merge duplicate rows."""
    merged = {}
    for raw in rows or []:
        name = canonical_model(raw.get("modelName") or raw.get("model"))
        if not name:
            continue
        row = merged.setdefault(
            name,
            {"modelName": name, **{c: 0 for c in COMPONENTS}, "cost": 0.0},
        )
        for c in COMPONENTS:
            row[c] += raw.get(c, 0) or 0
        row["cost"] += raw.get("cost", 0) or 0
    return sorted(
        (
            row
            for row in merged.values()
            if model_total(row) > 0 or row["cost"] > 0
        ),
        key=lambda row: (-model_total(row), -row["cost"], row["modelName"]),
    )


def aggregate_model_map(models):
    return {
        row["modelName"]: row
        for row in aggregate_breakdowns(
            {"modelName": name, **values}
            for name, values in (models or {}).items()
        )
    }


def replace_agent_month(month, reported, corrected, reported_model_predicate=None):
    """Replace one ccusage agent slice with its independently verified truth."""
    for c in COMPONENTS + ["totalTokens"]:
        month[c] = max(0, month.get(c, 0) - reported.get(c, 0)) + corrected.get(c, 0)

    grouped = {
        row["modelName"]: row
        for row in aggregate_breakdowns(month.get("modelBreakdowns", []))
    }
    reported_models = aggregate_model_map(reported.get("models"))
    corrected_models = aggregate_model_map(corrected.get("models"))
    if reported_model_predicate:
        for key, row in grouped.items():
            if key not in reported_models and reported_model_predicate(key):
                reported_models[key] = row
    for key, raw in reported_models.items():
        if key not in grouped:
            continue
        row = grouped[key]
        raw = dict(raw)
        raw_total = model_total(raw)
        row_total = model_total(row)
        if not raw.get("cost") and raw_total > 0 and row_total > 0:
            raw["cost"] = row.get("cost", 0) * min(1.0, raw_total / row_total)
            reported_models[key] = raw
        for c in COMPONENTS:
            row[c] = max(0, row[c] - (raw.get(c, 0) or 0))
        row["cost"] = max(0.0, row["cost"] - (raw.get("cost", 0) or 0))

    for key, raw in corrected_models.items():
        row = grouped.setdefault(
            key,
            {"modelName": key, **{c: 0 for c in COMPONENTS}, "cost": 0.0},
        )
        for c in COMPONENTS:
            row[c] += raw.get(c, 0) or 0
        reported_row = reported_models.get(key)
        reported_total = model_total(reported_row or {})
        if reported_row and reported_total > 0:
            row["cost"] += (reported_row.get("cost", 0) or 0) * model_total(raw) / reported_total

    month["modelBreakdowns"] = aggregate_breakdowns(grouped.values())
    month["modelsUsed"] = [row["modelName"] for row in month["modelBreakdowns"]]


def cap_model_breakdowns(month):
    """Keep attributed model components within their verified month totals."""
    rows = aggregate_breakdowns(month.get("modelBreakdowns", []))
    for component in COMPONENTS:
        cap = int(month.get(component, 0) or 0)
        values = [int(row.get(component, 0) or 0) for row in rows]
        assigned = sum(values)
        if assigned <= cap or assigned == 0:
            continue
        allocations = []
        for index, value in enumerate(values):
            scaled, remainder = divmod(value * cap, assigned)
            rows[index][component] = scaled
            allocations.append((remainder, rows[index]["modelName"], index))
        remaining = cap - sum(row[component] for row in rows)
        for _, _, index in sorted(allocations, key=lambda item: (-item[0], item[1]))[:remaining]:
            rows[index][component] += 1

    cost_cap = float(month.get("totalCost", 0) or 0)
    assigned_cost = sum(float(row.get("cost", 0) or 0) for row in rows)
    if assigned_cost > cost_cap and assigned_cost > 0:
        factor = cost_cap / assigned_cost
        for row in rows:
            row["cost"] = float(row.get("cost", 0) or 0) * factor
    return aggregate_breakdowns(rows)


def infer_single_reported_model(reported, corrected):
    """Keep a verified identity when the true counter only lacks model splits."""
    if corrected.get("models") or len(reported.get("models") or {}) != 1:
        return corrected
    name = next(iter(reported["models"]))
    out = dict(corrected)
    out["models"] = {name: {c: corrected.get(c, 0) for c in COMPONENTS}}
    out["models"][name]["totalTokens"] = corrected.get("totalTokens", 0)
    return out


def conserve_agent_rows(agent):
    floor_total_tokens(agent["totals"])
    for month in agent["monthly"]:
        floor_total_tokens(month)
        for model in (month.get("models") or {}).values():
            floor_total_tokens(model)


def main():
    d = pathlib.Path(sys.argv[1])
    unified = load(d, "monthly.json")
    daily = load(d, "daily.json")
    for day in daily["daily"]:
        floor_total_tokens(day)
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
        hermes = load(d, "hermes-true.json")
    except FileNotFoundError:
        hermes = {"totals": {}, "monthly": []}
    try:
        kimi_true = load(d, "kimi-true.json")
    except FileNotFoundError:
        kimi_true = {"totals": {}, "monthly": []}
    try:
        sources = load(d, "sources.json")
    except FileNotFoundError:
        sources = []

    codex_rep = {m["month"]: m for m in agents_raw["codex"].get("monthly") or []}
    codex_tru = {m["month"]: m for m in codex_true.get("monthly") or []}
    kimi_rep = {m["month"]: m for m in agents_raw["kimi"].get("monthly") or []}
    kimi_tru = {m["month"]: m for m in kimi_true["monthly"]}

    def rep_total(rep):
        return rep.get("totalTokens") or sum(rep.get(c, 0) for c in COMPONENTS)

    if rep_total(agents_raw["codex"].get("totals") or {}) > 0 and rep_total(codex_true.get("totals") or {}) <= 0:
        raise RuntimeError("codex true counter is empty while ccusage reported data")
    if rep_total(agents_raw["kimi"].get("totals") or {}) > 0 and rep_total(kimi_true.get("totals") or {}) <= 0:
        raise RuntimeError("kimi true counter is empty while ccusage reported data")

    monthly = []
    for m in unified["monthly"]:
        m = dict(m)
        month = m["period"]

        # ccusage's Codex adapter sums repeated cumulative token_count events.
        # Replace that slice before adding side sources or the frozen baseline.
        crep = codex_rep.get(month)
        if crep:
            replace_agent_month(
                m,
                crep,
                codex_tru.get(month, {"models": {}}),
                reported_model_predicate=lambda name: "codex" in name,
            )

        # Correct kimi (ccusage reads user-history, missing token metadata).
        krep = kimi_rep.get(month)
        ktru = kimi_tru.get(month)
        if krep and rep_total(krep):
            replace_agent_month(m, krep, infer_single_reported_model(krep, ktru or {"models": {}}))

        # Rebuild the month's cost from the (possibly corrected) model rows.
        breakdowns = []
        total_cost = 0.0
        for b in m.get("modelBreakdowns", []):
            total_cost += b.get("cost", 0)
            breakdowns.append(dict(b))
        m["modelBreakdowns"] = breakdowns
        m["totalCost"] = total_cost
        floor_total_tokens(m)
        monthly.append(m)

    # Merge a token-accounted side source (cursor dashboard, grok logs) into the
    # unified monthly series — each contributes its own components + model rows.
    by_period = {m["period"]: m for m in monthly}

    def merge_source(src, label):
        for raw_month in src.get("monthly") or []:
            cm = dict(raw_month)
            floor_total_tokens(cm)
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
    merge_source(hermes, "hermes")  # cloud swarm gateway; only visible in its sqlite DBs
    if rep_total(hermes.get("totals") or {}) > 0:
        # monthly.json only describes ccusage's direct/mirrored cloud logs.
        # Preserve the Hermes side ledger as its own source so README fleet
        # totals include every cloud profile and offline cache fallback.
        sources = list(sources) + [{
            "label": "cloud-hermes",
            "totals": copy.deepcopy(hermes.get("totals") or {}),
        }]

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
        for raw_month in baseline.get("monthly", []):
            bm = dict(raw_month)
            floor_total_tokens(bm)
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
        for raw_day in baseline.get("daily", []):
            bd = dict(raw_day)
            floor_total_tokens(bd)
            dd = by_day.get(bd["period"])
            if dd is None:
                continue  # outside the live 35-day window; totals come from monthly
            for c in COMPONENTS + ["totalTokens", "totalCost"]:
                dd[c] = dd.get(c, 0) + bd.get(c, 0)

    # One public row per real model. Placeholder router labels remain counted
    # in all-time totals but are intentionally left unattributed.
    for m in monthly:
        floor_total_tokens(m)
        m["modelBreakdowns"] = cap_model_breakdowns(m)
        m["modelsUsed"] = [row["modelName"] for row in m["modelBreakdowns"]]
    for day in daily["daily"]:
        floor_total_tokens(day)

    monthly.sort(key=lambda m: m["period"])

    totals = {c: sum(m.get(c, 0) for m in monthly) for c in COMPONENTS}
    totals["totalTokens"] = sum(m["totalTokens"] for m in monthly)
    totals["totalCost"] = sum(m["totalCost"] for m in monthly)
    floor_total_tokens(totals)

    agents = {}
    for name, raw in agents_raw.items():
        agents[name] = {
            "totals": copy.deepcopy(raw.get("totals") or {}),
            "monthly": copy.deepcopy(raw.get("monthly") or []),
        }
    # Use the same corrected Codex scope in the per-agent receipt.
    agents["codex"] = {
        "totals": copy.deepcopy(codex_true.get("totals") or {}),
        "monthly": copy.deepcopy(codex_true.get("monthly") or []),
    }
    agents["cursor"] = {
        "totals": copy.deepcopy(cursor.get("totals") or {}),
        "monthly": copy.deepcopy(cursor.get("monthly") or []),
    }
    agents["grok"] = {
        "totals": copy.deepcopy(grok.get("totals") or {}),
        "monthly": copy.deepcopy(grok.get("monthly") or []),
    }
    agents["kimi"] = {
        "totals": copy.deepcopy(kimi_true.get("totals") or {}),
        "monthly": copy.deepcopy(kimi_true.get("monthly") or []),
    }
    agents["hermes"] = {
        "totals": copy.deepcopy(hermes.get("totals") or {}),
        "monthly": copy.deepcopy(hermes.get("monthly") or []),
    }
    for agent in agents.values():
        conserve_agent_rows(agent)

    if baseline:
        for name, b in (baseline.get("agents") or {}).items():
            a = agents.setdefault(name, {"totals": {}, "monthly": []})
            at = a["totals"]
            baseline_totals = dict(b.get("totals", {}))
            floor_total_tokens(baseline_totals)
            for c in COMPONENTS + ["totalTokens", "totalCost"]:
                at[c] = at.get(c, 0) + baseline_totals.get(c, 0)
            by_month = {m["month"]: m for m in a["monthly"]}
            for raw_month in b.get("monthly", []):
                bm = copy.deepcopy(raw_month)
                floor_total_tokens(bm)
                for model in (bm.get("models") or {}).values():
                    floor_total_tokens(model)
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

    for agent in agents.values():
        conserve_agent_rows(agent)
    for source in sources:
        if isinstance(source.get("totals"), dict):
            floor_total_tokens(source["totals"])

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
            "accountingRevision": ACCOUNTING_REVISION,
            "codexCumulativeAdjusted": True,
            "codexReportedTotal": agents_raw["codex"].get("totals", {}).get("totalTokens"),
            "codexTrueTotal": codex_true.get("totals", {}).get("totalTokens"),
            "kimiWireAdjusted": True,
            "kimiReportedTotal": agents_raw["kimi"].get("totals", {}).get("totalTokens"),
            "kimiTrueTotal": kimi_true["totals"].get("totalTokens"),
            "cloudHermesAccounted": rep_total(hermes.get("totals") or {}) > 0,
            "cloudHermesTotal": hermes.get("totals", {}).get("totalTokens", 0),
            "componentTotalsConserved": True,
            "note": (
                "codex counted from monotonic total_token_usage deltas; repeated token_count events removed. "
                "kimi counted from ~/.kimi/sessions/**/wire.jsonl StatusUpdate "
                "token_usage; ccusage reads user-history and undercounts. "
                "complete component rows are floored at input + output + cache write + cache read "
                "while larger provider totals preserve unclassified/reasoning tokens. "
                "daily[] period components remain as reported (relative shape only)."
            ),
        },
    }
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
