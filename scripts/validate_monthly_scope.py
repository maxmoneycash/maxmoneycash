"""Require a complete native monthly scope with Grok excluded at its source."""
import json
import math
import sys

from token_accounting import COMPONENTS

COUNTS = COMPONENTS + ["totalTokens"]


def validate(report):
    def require(ok, message):
        if not ok:
            raise ValueError("Unsafe monthly scanner scope: " + message)

    def counts(row):
        require(isinstance(row, dict) and all(type(row.get(k)) is int and row[k] >= 0 for k in COUNTS),
                "invalid counters")
        require(row["totalTokens"] >= sum(row[k] for k in COMPONENTS), "invalid headline")
        cost = row.get("totalCost")
        require(type(cost) in (int, float) and math.isfinite(cost) and cost >= 0, "invalid cost")

    def conserved(parent, children):
        counts(parent)
        for child in children:
            counts(child)
        require(all(parent[k] == sum(c[k] for c in children) for k in COUNTS),
                "agent or month token totals disagree")
        require(math.isclose(parent["totalCost"], sum(c["totalCost"] for c in children),
                             rel_tol=1e-9, abs_tol=1e-8), "agent or month costs disagree")

    require(isinstance(report, dict) and isinstance(report.get("monthly"), list), "missing months")
    periods = set()
    for month in report["monthly"]:
        require(isinstance(month, dict), "invalid month")
        period = month.get("period")
        require(isinstance(period, str) and period and period not in periods, "invalid or duplicate period")
        periods.add(period)
        agents = month.get("agents")
        require(isinstance(agents, list), "missing --by-agent breakdown")
        names = []
        for agent in agents:
            require(isinstance(agent, dict) and isinstance(agent.get("agent"), str) and agent["agent"],
                    "invalid agent")
            names.append(agent["agent"])
        require(len(names) == len(set(names)), "duplicate agents")
        require("grok" not in names, "native Grok was not excluded")
        metadata = month.get("metadata")
        require(isinstance(metadata, dict) and isinstance(metadata.get("agents"), list), "missing source names")
        require(sorted(metadata["agents"]) == sorted(names), "source names disagree")
        conserved(month, agents)
        models = month.get("modelBreakdowns")
        require(isinstance(models, list), "missing model breakdown")
        for model in models:
            require(isinstance(model, dict) and isinstance(model.get("modelName"), str) and model["modelName"],
                    "invalid model")
            require(all(type(model.get(k)) is int and model[k] >= 0 for k in COMPONENTS), "invalid model counters")
            cost = model.get("cost")
            require(type(cost) in (int, float) and math.isfinite(cost) and cost >= 0, "invalid model cost")
        require(all(sum(m[k] for m in models) == month[k] for k in COMPONENTS), "model counters disagree")
        require(math.isclose(sum(m["cost"] for m in models), month["totalCost"],
                             rel_tol=1e-9, abs_tol=1e-8), "model costs disagree")
    conserved(report.get("totals"), report["monthly"])


if __name__ == "__main__":
    with open(sys.argv[1]) as source:
        validate(json.load(source))
