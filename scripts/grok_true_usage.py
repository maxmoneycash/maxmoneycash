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
Per-inference logs carry no model name, so usage is bucketed under "grok-build".

Outputs the accumulated {totals, monthly:[...]} (cursor/codex schema) to stdout.
"""
import datetime
import glob
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "grok-cache.json"
GROK_HOME = pathlib.Path(os.environ.get("GROK_HOME", pathlib.Path.home() / ".grok"))
MODEL = "grok-build"
COMPONENTS = ["inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens"]
SEEN_CAP = 100_000  # rolling log means old ids never reappear; bound cache size


def empty_month():
    return {"inputTokens": 0, "outputTokens": 0, "cacheCreationTokens": 0,
            "cacheReadTokens": 0, "totalTokens": 0, "calls": 0}


def load_cache():
    try:
        c = json.loads(CACHE.read_text())
        c.setdefault("monthly", {})
        c.setdefault("seen", [])
        return c
    except Exception:
        return {"monthly": {}, "seen": []}


def main():
    cache = load_cache()
    monthly = cache["monthly"]
    seen = set(cache["seen"])
    new_ids = []

    for fp in sorted(glob.glob(str(GROK_HOME / "logs" / "*.jsonl*"))):
        for line in open(fp, errors="ignore"):
            if '"prompt_tokens"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            ctx = d.get("ctx") or {}
            if "prompt_tokens" not in ctx:
                continue
            ts = d.get("ts") or ""
            eid = f"{d.get('sid','')}|{ts}|{ctx.get('loop_index','')}|{ctx.get('prompt_tokens')}"
            if eid in seen:
                continue
            seen.add(eid)
            new_ids.append(eid)
            month = ts[:7] or "unknown"
            m = monthly.setdefault(month, empty_month())
            prompt = ctx.get("prompt_tokens", 0) or 0
            cached = ctx.get("cached_prompt_tokens", 0) or 0
            out = (ctx.get("completion_tokens", 0) or 0) + (ctx.get("reasoning_tokens", 0) or 0)
            inp = max(prompt - cached, 0)
            m["inputTokens"] += inp
            m["cacheReadTokens"] += cached
            m["outputTokens"] += out
            m["totalTokens"] += inp + cached + out
            m["calls"] += 1

    # persist cache (bound the seen list)
    all_seen = cache["seen"] + new_ids
    if len(all_seen) > SEEN_CAP:
        all_seen = all_seen[-SEEN_CAP:]
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps({"monthly": monthly, "seen": all_seen}))

    # build output in the cursor/codex monthly schema
    out_monthly = []
    for month in sorted(monthly):
        m = monthly[month]
        out_monthly.append({
            "month": month,
            "inputTokens": m["inputTokens"], "outputTokens": m["outputTokens"],
            "cacheCreationTokens": 0, "cacheReadTokens": m["cacheReadTokens"],
            "totalTokens": m["totalTokens"], "totalCost": 0.0,
            "models": {MODEL: {
                "inputTokens": m["inputTokens"], "outputTokens": m["outputTokens"],
                "cacheCreationTokens": 0, "cacheReadTokens": m["cacheReadTokens"],
                "totalTokens": m["totalTokens"], "cost": 0.0,
            }},
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
