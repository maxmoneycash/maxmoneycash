#!/usr/bin/env python3
"""codex_true_usage.py - true token accounting for Codex CLI session rollouts.

Why this exists
---------------
ccusage v20's codex adapter sums the per-event ``last_token_usage`` payload of
every ``token_count`` event in ``~/.codex/sessions/**/*.jsonl``. Codex re-emits
``token_count`` events (UI refreshes, replays) without the cumulative counter
moving, so ccusage double-counts those re-emitted events (e.g. a session whose
cumulative counter ends at 3,300 tokens is reported as 5,500).

This script instead derives usage from the *cumulative* ``total_token_usage``
counter, which is monotonic within a counter lifetime:

* a delta is recorded only when the cumulative ``total_tokens`` moves;
* re-emitted events (cumulative unchanged) contribute nothing;
* counter resets (cumulative decreases) start a new baseline and the new
  cumulative value is counted as the first delta of the new counter;
* forked/subagent rollout files (``forked_from_id`` in ``session_meta`` /
  ``subagent.thread_spawn`` source) replay the parent thread's entire history
  -- including its token_count trajectory -- in a synchronous write burst at
  spawn time.  Those replayed events duplicate usage already recorded in the
  parent's own rollout file, so they only establish the baseline and are never
  counted.  Replay events are identified by their timestamp falling within
  REPLAY_WINDOW_SECONDS of the file's session_meta timestamp (observed bursts
  finish < 0.4 s after spawn; the first genuine post-spawn event arrives
  seconds later).

Field mapping (verified against real rollouts, all of which satisfy
``total_tokens == input_tokens + output_tokens``; ``input_tokens`` INCLUDES
``cached_input_tokens``):

* inputTokens          = delta(input_tokens) - delta(cached_input_tokens)
* cacheReadTokens      = delta(cached_input_tokens)
* outputTokens         = delta(output_tokens)  (reasoning is folded in here)
* cacheCreationTokens  = 0  (codex does not report cache writes)
* totalTokens          = inputTokens + cacheReadTokens + outputTokens

Usage: ``python3 codex_true_usage.py``  (honors $CODEX_HOME, default ~/.codex)
Output: JSON on stdout - overall totals plus per-UTC-month, per-model rollups.
Deterministic, stdlib only, single pass per file.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

REPLAY_WINDOW_SECONDS = 5.0


def parse_ts(value):
    """Parse an ISO-8601 timestamp ('...Z' or offset) to an aware datetime."""
    if not value or not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def session_files(codex_home):
    root = os.path.join(codex_home, "sessions")
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if name.endswith(".jsonl"):
                out.append(os.path.join(dirpath, name))
    return out


def new_bucket():
    return {
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheCreationTokens": 0,
        "cacheReadTokens": 0,
        "totalTokens": 0,
    }


def add_delta(bucket, d_input, d_cached, d_output):
    non_cached = max(0, d_input - d_cached)
    bucket["inputTokens"] += non_cached
    bucket["cacheReadTokens"] += d_cached
    bucket["outputTokens"] += d_output
    bucket["totalTokens"] += non_cached + d_cached + d_output


def process_file(path, totals, monthly, monthly_models):
    meta_ts = None
    is_fork = False
    model = "unknown"
    prev = None  # (input, cached, output, total) cumulative tuple

    with open(path, "r", errors="replace") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            rtype = obj.get("type")
            payload = obj.get("payload")
            if not isinstance(payload, dict):
                continue

            if rtype == "session_meta" and meta_ts is None:
                meta_ts = parse_ts(obj.get("timestamp")) or parse_ts(
                    payload.get("timestamp")
                )
                source = payload.get("source")
                spawned = isinstance(source, dict) and "subagent" in source
                is_fork = bool(payload.get("forked_from_id")) or spawned

            elif rtype == "turn_context":
                m = payload.get("model")
                if isinstance(m, str) and m:
                    model = m

            elif rtype == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info")
                if not isinstance(info, dict):
                    continue
                tt = info.get("total_token_usage")
                if not isinstance(tt, dict):
                    continue
                cur = (
                    tt.get("input_tokens") or 0,
                    tt.get("cached_input_tokens") or 0,
                    tt.get("output_tokens") or 0,
                    tt.get("total_tokens") or 0,
                )
                ts = parse_ts(obj.get("timestamp"))

                # Replayed parent history at the head of a forked/subagent
                # rollout: baseline only, never counted (already recorded in
                # the parent's own rollout file).
                replay = (
                    is_fork
                    and meta_ts is not None
                    and ts is not None
                    and (ts - meta_ts).total_seconds() < REPLAY_WINDOW_SECONDS
                )
                if replay:
                    prev = cur
                    continue

                if prev is None:
                    delta = cur  # first observation of a fresh counter
                elif cur[3] == prev[3]:
                    delta = None  # re-emitted event: the ccusage v20 bug
                elif cur[3] < prev[3]:
                    delta = cur  # counter reset: new counter starts here
                else:
                    delta = tuple(max(0, a - b) for a, b in zip(cur, prev))
                prev = cur
                if delta is None:
                    continue

                d_input, d_cached, d_output, _ = delta
                if d_input == 0 and d_cached == 0 and d_output == 0:
                    continue

                event_ts = ts or meta_ts
                month = (
                    event_ts.astimezone(timezone.utc).strftime("%Y-%m")
                    if event_ts
                    else "unknown"
                )
                add_delta(totals, d_input, d_cached, d_output)
                add_delta(monthly[month], d_input, d_cached, d_output)
                add_delta(monthly_models[month][model], d_input, d_cached, d_output)


def main():
    codex_home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    totals = new_bucket()
    monthly = defaultdict(new_bucket)
    monthly_models = defaultdict(lambda: defaultdict(new_bucket))

    for path in session_files(codex_home):
        try:
            process_file(path, totals, monthly, monthly_models)
        except OSError:
            continue

    months = []
    for month in sorted(monthly):
        entry = {"month": month}
        entry.update(monthly[month])
        entry["models"] = {
            name: monthly_models[month][name]
            for name in sorted(monthly_models[month])
        }
        months.append(entry)

    json.dump({"totals": totals, "monthly": months}, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
