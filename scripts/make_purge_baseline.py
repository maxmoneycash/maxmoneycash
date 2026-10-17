#!/usr/bin/env python3
"""make_purge_baseline.py - freeze usage whose local transcripts were deleted.

On 2026-10-12 a disk cleanup deleted this Mac's Claude Code
(~/.claude/projects/*.jsonl) and Codex (~/.codex/sessions) transcripts older
than 60 days, or older than 30 days and larger than 300 MB. The collector
recounts everything from raw transcripts on every run, so that usage vanished
from each fresh scan (~94B against the 126.56B ledger) and the monotonic guard
has refused every run since 2026-10-13T05:50Z.

Same method as make_cloud_baseline.py:

    baseline = last good tokens.json - a fresh rebuild from surviving transcripts

per month x agent x model, floored at zero, for FINISHED months only: months
before --open-month (default: the month the old ledger was built in, which was
still accruing). The open month and later belong to the fresh scans, and a
finished month the fresh scan still fully covers (fresh total >= old total)
contributes nothing. Row totals are the exact difference of the two totals and
components are fitted under them, so fresh + baseline reproduces every finished
month's total, components and cost exactly, and every per-agent row exactly
down to each model. The unified monthly modelBreakdowns are not always exact:
where the old build had dropped an orphan row (the Codex replacement removes
other "*codex*" rows when Codex has a month), the fresh build keeps it, and
build_tokens_json.py's cap_model_breakdowns rescales the merged rows to the
month's components. For the 2026-10-12 purge that moved model attribution in
2026-04, 2026-07 and 2026-08 (e.g. Apr gpt-5.3-codex +169.7M, gpt-5.5 -77.1M;
Jul gpt-5.6-sol -127.3M) and finished-month list value by +$3.11.

A scan that timed out looks exactly like purged data: frozen into the baseline,
it would double count as soon as the scan recovered. So the fresh rebuild must
run TWICE, each as a strict sandboxed audit run, and this script refuses unless

  - both audit dirs have an empty scan-failures.txt (nothing failed or timed out),
  - neither fresh build already contains a purge baseline,
  - both match the old ledger's accounting revision and source labels,
  - every agent with usage in the old ledger still has usage in both, and only
    the agents named by --purged-agents lose usage in finished months,
  - both agree exactly on every finished month (monthly, agents, shared days).

Usage (outputs stay in $S; data/tokens.json is only read):

    S=/path/to/scratch
    for n in 1 2; do
      TOKENSTATS_AUDIT_DIR=$S/fresh-$n TOKENSTATS_OFFLINE=1 \\
      TOKENSTATS_STRICT_SCANS=1 TOKENSTATS_PURGE_BASELINE=none \\
      TOKENSTATS_SCAN_TIMEOUT=5400 bash scripts/collect_tokens.sh
    done  # each exits 1: the guard refuses the low total; tokens.json is kept
    git show 2d609b34:data/tokens.json > $S/last-good.json
    python3 scripts/make_purge_baseline.py $S/last-good.json $S/fresh-1 $S/fresh-2 \\
        --out data/local-purge-baseline.json

--out writes atomically and only on success; a refusal leaves the file as it was.

build_tokens_json.py adds data/local-purge-baseline.json into every build
(collect_tokens.sh passes it after data/cloud-baseline.json).

After any later transcript deletion, re-run the same procedure against the
last good ledger built BEFORE that deletion (it already carries the current
local-purge-baseline). The fresh builds exclude the purge baseline
(TOKENSTATS_PURGE_BASELINE=none), so old - fresh is everything purged so far,
the old purge plus the new one, and the output replaces data/local-purge-
baseline.json as a whole. Never add a second purge baseline on top.
"""
import argparse
import json
import pathlib
import sys

from token_accounting import COMPONENTS

LABEL = "local-purge-baseline"
DEFAULT_PURGED_AGENTS = ("claude", "codex")


class BaselineError(Exception):
    pass


# --- row arithmetic -----------------------------------------------------------

def _num(row, key):
    return row.get(key, 0) or 0


def component_sum(row):
    return sum(_num(row, c) for c in COMPONENTS)


def fit_under(rows, component, cap):
    """Scale one component across rows so it sums to at most cap (largest remainder)."""
    assigned = sum(r[component] for r in rows)
    if assigned <= cap or assigned == 0:
        return
    remainders = []
    for index, r in enumerate(rows):
        scaled, remainder = divmod(r[component] * cap, assigned)
        r[component] = scaled
        remainders.append((remainder, index))
    left = cap - sum(r[component] for r in rows)
    for _, index in sorted(remainders, key=lambda item: (-item[0], item[1]))[:left]:
        rows[index][component] += 1


def fit_components(row, cap):
    """Shrink a row's components (proportionally) so they sum to at most cap."""
    total = component_sum(row)
    if total <= cap:
        return
    cells = [{"v": row[c]} for c in COMPONENTS]
    fit_under(cells, "v", cap)
    for c, cell in zip(COMPONENTS, cells):
        row[c] = cell["v"]


def sub_row(old, new):
    """old - new for one period row: the headline is the exact (floored)
    difference of the two totals; components and cost are floored at zero and
    the components fitted under that headline, so old == new + result."""
    row = {c: max(0, _num(old, c) - _num(new, c)) for c in COMPONENTS}
    total = max(0, _num(old, "totalTokens") - _num(new, "totalTokens"))
    fit_components(row, total)
    row["totalTokens"] = total
    row["totalCost"] = max(0.0, float(_num(old, "totalCost")) - float(_num(new, "totalCost")))
    return row


def model_map_from_breakdowns(breakdowns):
    out = {}
    for b in breakdowns or []:
        name = b.get("modelName") or b.get("model") or "unknown"
        row = out.setdefault(name, {**{c: 0 for c in COMPONENTS}, "cost": 0.0})
        for c in COMPONENTS:
            row[c] += _num(b, c)
        row["cost"] += float(_num(b, "cost"))
    return out


def model_map_from_models(models):
    out = {}
    for name, m in (models or {}).items():
        out[name] = {**{c: _num(m, c) for c in COMPONENTS}, "cost": float(_num(m, "cost"))}
    return out


def sub_models(old_models, new_models, month_row):
    """Per-model old - new, floored at zero, then capped to the month row so
    attributed models never exceed the month's own components or cost."""
    out = {}
    for name, o in sorted(old_models.items()):
        n = new_models.get(name, {})
        r = {c: max(0, _num(o, c) - _num(n, c)) for c in COMPONENTS}
        r["cost"] = max(0.0, float(_num(o, "cost")) - float(_num(n, "cost")))
        if component_sum(r) > 0 or r["cost"] > 0:
            out[name] = r
    rows = list(out.values())
    for c in COMPONENTS:
        fit_under(rows, c, month_row[c])
    cost_cap = month_row["totalCost"]
    assigned_cost = sum(r["cost"] for r in rows)
    if assigned_cost > cost_cap and assigned_cost > 0:
        factor = cost_cap / assigned_cost
        for r in rows:
            r["cost"] *= factor
    result = {}
    for name, r in out.items():
        r["totalTokens"] = component_sum(r)
        if r["totalTokens"] > 0 or r["cost"] > 0:
            result[name] = r
    return result


# --- what a baseline may freeze ----------------------------------------------

def finished(period, open_month):
    return period[:7] < open_month


def _cost(value):
    return round(float(value or 0), 6)


def signature(row, models=None):
    sig = tuple(_num(row, c) for c in COMPONENTS) + (
        _num(row, "totalTokens"),
        _cost(row.get("totalCost", row.get("cost"))),
    )
    if models is not None:
        sig += (tuple(
            (name,) + tuple(_num(m, c) for c in COMPONENTS) + (_cost(m.get("cost")),)
            for name, m in sorted(models.items())
        ),)
    return sig


def finished_view(ledger, open_month):
    """Everything a baseline built from this ledger would freeze, comparably."""
    view = {}
    for m in ledger.get("monthly") or []:
        if finished(m["period"], open_month):
            view[("monthly", m["period"])] = signature(
                m, model_map_from_breakdowns(m.get("modelBreakdowns")))
    for name, agent in (ledger.get("agents") or {}).items():
        for m in agent.get("monthly") or []:
            if finished(m["month"], open_month):
                view[("agent", name, m["month"])] = signature(
                    m, model_map_from_models(m.get("models")))
    for d in ledger.get("daily") or []:
        if finished(d["period"], open_month):
            view[("daily", d["period"])] = signature(d)
    return view


def check_agreement(fresh_a, fresh_b, open_month):
    """Both rebuilds must agree on every finished month. Daily rows are
    compared on the days both 35-day windows contain."""
    va, vb = finished_view(fresh_a, open_month), finished_view(fresh_b, open_month)
    days_a = {k for k in va if k[0] == "daily"}
    days_b = {k for k in vb if k[0] == "daily"}
    shared_days = days_a & days_b
    keys = ({k for k in va if k[0] != "daily"} | {k for k in vb if k[0] != "daily"}
            | shared_days)
    diffs = sorted(k for k in keys if va.get(k) != vb.get(k))
    if diffs:
        shown = ", ".join("/".join(k) for k in diffs[:12])
        raise BaselineError(
            f"the two fresh rebuilds disagree on {len(diffs)} finished-month "
            f"row(s): {shown}. A scan was partial or the data moved; re-run both."
        )
    return len(keys)


def source_labels(ledger):
    return sorted(s.get("label", "") for s in ledger.get("sources") or [])


def agent_total(ledger, name):
    return _num(((ledger.get("agents") or {}).get(name) or {}).get("totals") or {}, "totalTokens")


def validate_fresh(old, fresh, name, allow_vanished=()):
    labels = source_labels(fresh)
    if LABEL in labels:
        raise BaselineError(
            f"{name} already includes {LABEL}; rebuild it with "
            "TOKENSTATS_PURGE_BASELINE=none")
    old_rev = (old.get("corrections") or {}).get("accountingRevision")
    new_rev = (fresh.get("corrections") or {}).get("accountingRevision")
    if old_rev != new_rev:
        raise BaselineError(f"{name}: accounting revision {new_rev!r} != old {old_rev!r}")
    # The old ledger may already carry a purge baseline (a re-run after a
    # later deletion): old - fresh then covers the previous purge too, and
    # the new file replaces the old one.
    old_labels = [label for label in source_labels(old) if label != LABEL]
    if labels != old_labels:
        raise BaselineError(
            f"{name}: sources {labels} differ from the old ledger's "
            f"{old_labels} (e.g. the cloud box answered in one but not "
            "the other); rebuild with the same source set")
    for agent in sorted((old.get("agents") or {})):
        if agent_total(old, agent) > 0 and agent_total(fresh, agent) <= 0 \
                and agent not in allow_vanished:
            raise BaselineError(
                f"{name}: agent {agent!r} has no usage at all in the fresh "
                "rebuild; a vanished agent is a failed scan, not a purge")
    if (fresh.get("generated_at") or "") <= (old.get("generated_at") or ""):
        raise BaselineError(f"{name} is not newer than the old ledger")


# --- baseline -----------------------------------------------------------------

def sub_series(old_rows, new_rows, key, open_month, models_of=None, models_key=None):
    new_by = {r[key]: r for r in new_rows or []}
    out = []
    for o in sorted(old_rows or [], key=lambda r: r[key]):
        period = o[key]
        if not finished(period, open_month):
            continue
        n = new_by.get(period, {})
        if _num(n, "totalTokens") >= _num(o, "totalTokens"):
            continue  # the fresh scan still fully covers this period
        row = {key: period, **sub_row(o, n)}
        if row["totalTokens"] <= 0:
            continue
        if models_of is not None:
            models = sub_models(models_of(o), models_of(n), row)
            if models_key == "modelBreakdowns":
                row["modelBreakdowns"] = [
                    {"modelName": m, **{c: v[c] for c in COMPONENTS}, "cost": v["cost"]}
                    for m, v in sorted(models.items())
                ]
            else:
                row["models"] = models
            row["modelsUsed"] = sorted(models)
        out.append(row)
    return out


def totals_of(rows):
    t = {c: sum(_num(r, c) for r in rows) for c in COMPONENTS}
    t["totalTokens"] = sum(_num(r, "totalTokens") for r in rows)
    t["totalCost"] = sum(float(_num(r, "totalCost")) for r in rows)
    return t


def compute_baseline(old, fresh, open_month, purged_agents=DEFAULT_PURGED_AGENTS):
    agents = {}
    for name, o in sorted((old.get("agents") or {}).items()):
        n = (fresh.get("agents") or {}).get(name) or {}
        rows = sub_series(
            o.get("monthly"), n.get("monthly"), "month", open_month,
            models_of=lambda r: model_map_from_models(r.get("models")),
            models_key="models",
        )
        if rows:
            agents[name] = {"totals": totals_of(rows), "monthly": rows}
    unexpected = sorted(set(agents) - set(purged_agents))
    if unexpected:
        detail = ", ".join(f"{a} {agents[a]['totals']['totalTokens']:,}" for a in unexpected)
        raise BaselineError(
            f"agents outside --purged-agents lost finished-month usage ({detail}); "
            "that is a partial scan, not the transcript purge")

    monthly = sub_series(
        old.get("monthly"), fresh.get("monthly"), "period", open_month,
        models_of=lambda r: model_map_from_breakdowns(r.get("modelBreakdowns")),
        models_key="modelBreakdowns",
    )
    for m in monthly:
        m["agent"] = "all"
        m["metadata"] = {"agents": sorted(
            name for name, a in agents.items()
            if any(r["month"] == m["period"] for r in a["monthly"])
        )}
    # Days before the fresh scan's 35-day window are out of range, not purged.
    fresh_days = sorted(d["period"] for d in fresh.get("daily") or [])
    daily = sub_series(
        [d for d in old.get("daily") or [] if fresh_days and d["period"] >= fresh_days[0]],
        fresh.get("daily"), "period", open_month,
    )

    return {
        "label": LABEL,
        "note": (
            "Frozen usage of this Mac's Claude Code/Codex transcripts deleted by "
            "the 2026-10-12 disk cleanup. Computed as the last good tokens.json "
            "minus a fresh rebuild from the surviving transcripts, finished "
            "months only. Added back into every build by build_tokens_json.py. "
            "Do not delete: this usage is unrecoverable from raw logs."
        ),
        "as_of": old.get("generated_at"),
        "fresh_generated_at": fresh.get("generated_at"),
        "open_month": open_month,
        "totals": totals_of(monthly),
        "monthly": monthly,
        "daily": daily,
        "agents": agents,
    }


def load_audit(path):
    d = pathlib.Path(path)
    failures = d / "scan-failures.txt"
    ledger = d / "tokens.json"
    if not failures.is_file() or not ledger.is_file():
        raise BaselineError(
            f"{d}: not a finished audit run (needs tokens.json and "
            "scan-failures.txt from TOKENSTATS_AUDIT_DIR)")
    text = failures.read_text().strip()
    if text:
        raise BaselineError(f"{d}: scans failed or timed out: {' | '.join(text.splitlines())}")
    return json.loads(ledger.read_text())


def summary(old, fresh, baseline):
    lines = []
    fresh_by = {m["period"]: m for m in fresh.get("monthly") or []}
    base_by = {m["period"]: m for m in baseline["monthly"]}
    for m in old.get("monthly") or []:
        p = m["period"]
        lines.append(
            f"  {p}  old {m['totalTokens']:>16,}  fresh "
            f"{_num(fresh_by.get(p, {}), 'totalTokens'):>16,}  baseline "
            f"{_num(base_by.get(p, {}), 'totalTokens'):>16,}")
    for name, a in baseline["agents"].items():
        months = ", ".join(f"{r['month']} {r['totalTokens']:,}" for r in a["monthly"])
        lines.append(f"  agent {name}: {a['totals']['totalTokens']:,} ({months})")
    lines.append(f"  total baseline {baseline['totals']['totalTokens']:,}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old", help="last good tokens.json")
    ap.add_argument("fresh_a", help="first strict audit dir (TOKENSTATS_AUDIT_DIR)")
    ap.add_argument("fresh_b", help="second strict audit dir")
    ap.add_argument("--open-month", help="first month NOT frozen (default: old generated_at month)")
    ap.add_argument("--purged-agents", default=",".join(DEFAULT_PURGED_AGENTS),
                    help="agents whose transcripts were deleted (default claude,codex)")
    ap.add_argument("--allow-vanished", default="",
                    help="agents allowed to have no usage in the fresh rebuilds")
    ap.add_argument("--out", help="write here atomically (default: stdout)")
    args = ap.parse_args(argv)

    try:
        old = json.loads(pathlib.Path(args.old).read_text())
        open_month = args.open_month or (old.get("generated_at") or "")[:7]
        if len(open_month) != 7:
            raise BaselineError("cannot tell the open month; pass --open-month YYYY-MM")
        allow = tuple(a for a in args.allow_vanished.split(",") if a)
        purged = tuple(a for a in args.purged_agents.split(",") if a)
        fresh_a, fresh_b = load_audit(args.fresh_a), load_audit(args.fresh_b)
        validate_fresh(old, fresh_a, args.fresh_a, allow)
        validate_fresh(old, fresh_b, args.fresh_b, allow)
        compared = check_agreement(fresh_a, fresh_b, open_month)
        baseline = compute_baseline(old, fresh_b, open_month, purged)
        baseline["agreement"] = {
            "fresh_runs": [fresh_a.get("generated_at"), fresh_b.get("generated_at")],
            "finished_rows_compared": compared,
        }
    except BaselineError as exc:
        print(f"make_purge_baseline: REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"make_purge_baseline: both rebuilds agree on {compared} finished-month rows "
          f"(open month {open_month})\n{summary(old, fresh_b, baseline)}", file=sys.stderr)
    text = json.dumps(baseline, indent=1, sort_keys=True) + "\n"
    if args.out:
        out = pathlib.Path(args.out)
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(text)
        tmp.replace(out)
        print(f"make_purge_baseline: wrote {out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
