"""Grok Build (xAI `grok` CLI) usage — parsed from ~/.grok/logs/unified.jsonl.

Grok logs one `shell.turn.inference_done` line per inference with a ctx of
prompt_tokens / cached_prompt_tokens / completion_tokens / reasoning_tokens.
That file is a single ROLLING log (no rotation history), so unlike Claude/Codex
we can't recompute from disk — we accumulate into data/grok-cache.json keyed by a
stable per-inference id, so re-runs never double-count and rotation never drops
already-captured usage.

Field mapping → tokens.json schema:
  inputTokens         = prompt_tokens - cached_prompt_tokens   (fresh input)
  cacheReadTokens     = cached_prompt_tokens
  outputTokens        = completion_tokens + reasoning_tokens
  cacheCreationTokens = 0  (grok reports none)

Grok runs on a subscription with no per-token price in our data, so cost = 0.
Per-inference logs carry no model name. The matching session event stream does,
so records still present on disk are joined to the active `turn_started.model_id`.
Historical cached usage whose raw record has rotated away remains `unknown`.

Outputs the accumulated {totals, monthly:[...]} (cursor/codex schema) to stdout.
"""
import bisect
import datetime
import glob
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "grok-cache.json"
GROK_HOME = pathlib.Path(os.environ.get("GROK_HOME", pathlib.Path.home() / ".grok"))
UNKNOWN_MODEL = "unknown"
CACHE_VERSION = 2
COMPONENTS = ["inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens"]
SEEN_CAP = 100_000  # rolling log means old ids never reappear; bound cache size


def empty_month():
    return {"inputTokens": 0, "outputTokens": 0, "cacheCreationTokens": 0,
            "cacheReadTokens": 0, "totalTokens": 0, "calls": 0, "models": {}}


def empty_model():
    return {"inputTokens": 0, "outputTokens": 0, "cacheCreationTokens": 0,
            "cacheReadTokens": 0, "totalTokens": 0}


def load_cache():
    try:
        c = json.loads(CACHE.read_text())
        c.setdefault("version", 1)
        c.setdefault("monthly", {})
        c.setdefault("seen", [])
        # A 2026-06-21 commit stored this script's OUTPUT (monthly as a list)
        # as the cache, which crashed every run since (monthly must be a dict
        # keyed by month). That stale list was verified on 2026-07-07 to be a
        # strict subset of the still-unrotated rolling log, so discarding it
        # and recounting from the log loses nothing and can't double-count.
        if not isinstance(c["monthly"], dict) or not isinstance(c["seen"], list):
            return {"version": CACHE_VERSION, "monthly": {}, "seen": []}
        return c
    except Exception:
        return {"version": CACHE_VERSION, "monthly": {}, "seen": []}


def model_timelines():
    timelines = {}
    pattern = str(GROK_HOME / "sessions" / "**" / "events.jsonl")
    for fp in sorted(glob.glob(pattern, recursive=True)):
        for line in open(fp, errors="ignore"):
            if '"turn_started"' not in line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if event.get("type") != "turn_started":
                continue
            session_id = event.get("session_id")
            timestamp = event.get("ts")
            model = event.get("model_id")
            if not session_id or not timestamp or not model:
                continue
            timelines.setdefault(session_id, []).append((timestamp, model))
    for events in timelines.values():
        events.sort()
    return timelines


def model_at(timelines, session_id, timestamp):
    events = timelines.get(session_id) or []
    if not events:
        return UNKNOWN_MODEL
    index = bisect.bisect_right([event[0] for event in events], timestamp) - 1
    if index < 0:
        return UNKNOWN_MODEL
    return events[index][1]


def usage_records(timelines):
    records = []
    seen_in_logs = set()
    for fp in sorted(glob.glob(str(GROK_HOME / "logs" / "*.jsonl*"))):
        for line in open(fp, errors="ignore"):
            if '"prompt_tokens"' not in line:
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue
            ctx = data.get("ctx") or {}
            if data.get("msg") != "shell.turn.inference_done" or "prompt_tokens" not in ctx:
                continue
            timestamp = data.get("ts") or ""
            session_id = data.get("sid") or ""
            event_id = (
                f"{session_id}|{timestamp}|{ctx.get('loop_index', '')}|"
                f"{ctx.get('prompt_tokens')}"
            )
            if event_id in seen_in_logs:
                continue
            seen_in_logs.add(event_id)
            prompt = ctx.get("prompt_tokens", 0) or 0
            cached = min(ctx.get("cached_prompt_tokens", 0) or 0, prompt)
            output = ((ctx.get("completion_tokens", 0) or 0)
                      + (ctx.get("reasoning_tokens", 0) or 0))
            components = {
                "inputTokens": max(prompt - cached, 0),
                "outputTokens": output,
                "cacheCreationTokens": 0,
                "cacheReadTokens": cached,
            }
            components["totalTokens"] = sum(components[c] for c in COMPONENTS)
            records.append({
                "id": event_id,
                "month": timestamp[:7] or "unknown",
                "model": model_at(timelines, session_id, timestamp),
                "usage": components,
            })
    return records


def add_usage(target, usage):
    for component in COMPONENTS + ["totalTokens"]:
        target[component] = target.get(component, 0) + usage.get(component, 0)


def migrate_legacy_months(monthly, records, seen):
    """Attribute cached rows that still have raw records, preserving old totals."""
    for month in monthly.values():
        legacy = {component: month.get(component, 0)
                  for component in COMPONENTS + ["totalTokens"]}
        month["models"] = {UNKNOWN_MODEL: legacy}
    for record in records:
        if record["id"] not in seen or record["month"] not in monthly:
            continue
        unknown = monthly[record["month"]]["models"][UNKNOWN_MODEL]
        usage = record["usage"]
        if any(unknown.get(component, 0) < usage.get(component, 0)
               for component in COMPONENTS + ["totalTokens"]):
            continue
        for component in COMPONENTS + ["totalTokens"]:
            unknown[component] -= usage[component]
        model = monthly[record["month"]]["models"].setdefault(
            record["model"], empty_model())
        add_usage(model, usage)
    for month in monthly.values():
        month["models"] = {
            model: usage for model, usage in month["models"].items()
            if usage.get("totalTokens", 0) > 0
        }


def main():
    cache = load_cache()
    monthly = cache["monthly"]
    seen = set(cache["seen"])
    new_ids = []
    records = usage_records(model_timelines())
    if cache.get("version", 1) < CACHE_VERSION:
        migrate_legacy_months(monthly, records, seen)
    for record in records:
        if record["id"] in seen:
            continue
        seen.add(record["id"])
        new_ids.append(record["id"])
        month = monthly.setdefault(record["month"], empty_month())
        add_usage(month, record["usage"])
        model = month.setdefault("models", {}).setdefault(
            record["model"], empty_model())
        add_usage(model, record["usage"])
        month["calls"] = month.get("calls", 0) + 1

    # persist cache (bound the seen list)
    all_seen = cache["seen"] + new_ids
    if len(all_seen) > SEEN_CAP:
        all_seen = all_seen[-SEEN_CAP:]
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps({
        "version": CACHE_VERSION, "monthly": monthly, "seen": all_seen,
    }))

    # build output in the cursor/codex monthly schema
    out_monthly = []
    for month in sorted(monthly):
        m = monthly[month]
        out_monthly.append({
            "month": month,
            "inputTokens": m["inputTokens"], "outputTokens": m["outputTokens"],
            "cacheCreationTokens": 0, "cacheReadTokens": m["cacheReadTokens"],
            "totalTokens": m["totalTokens"], "totalCost": 0.0,
            "models": {
                model: {**usage, "cost": 0.0}
                for model, usage in (m.get("models") or {}).items()
            },
        })
    totals = {c: sum(mm[c] for mm in out_monthly) for c in COMPONENTS}
    totals["totalTokens"] = sum(mm["totalTokens"] for mm in out_monthly)
    totals["totalCost"] = 0.0
    generated = (datetime.datetime.now(datetime.timezone.utc)
                 .isoformat(timespec="seconds").replace("+00:00", "Z"))
    json.dump({"totals": totals, "monthly": out_monthly, "generated_at": generated},
              sys.stdout)


if __name__ == "__main__":
    main()
