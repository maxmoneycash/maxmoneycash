#!/usr/bin/env python3
"""kimi_true_usage.py - true token accounting for Kimi Code CLI sessions.

ccusage's kimi adapter reads ~/.kimi/user-history/*.jsonl, which only contains
user prompts and misses the actual model responses and token metadata. This
script parses the real session wire logs at ~/.kimi/sessions/**/wire.jsonl and
sums the per-turn token_usage payloads from StatusUpdate events.

Field mapping from wire.jsonl StatusUpdate payloads:
  inputTokens         = input_other
  cacheReadTokens     = input_cache_read
  cacheCreationTokens = input_cache_creation
  outputTokens        = output
  totalTokens         = sum of the above

Usage: python3 kimi_true_usage.py
Output: JSON on stdout - overall totals plus per-UTC-month rollups.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

KIMI_HOME = os.environ.get("KIMI_HOME") or os.path.expanduser("~/.kimi")


def parse_ts(value):
    """Parse a unix timestamp (float seconds) to an aware datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (ValueError, TypeError):
        return None


def session_files(kimi_home):
    root = os.path.join(kimi_home, "sessions")
    out = []
    if not os.path.isdir(root):
        return out
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name == "wire.jsonl":
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def new_bucket():
    return {
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheCreationTokens": 0,
        "cacheReadTokens": 0,
        "totalTokens": 0,
    }


def process_file(path, totals, monthly):
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            msg = obj.get("message") if isinstance(obj.get("message"), dict) else None
            if not msg:
                continue
            if msg.get("type") != "StatusUpdate":
                continue

            payload = msg.get("payload") or {}
            tu = payload.get("token_usage") or {}
            if not tu:
                continue

            input_other = int(tu.get("input_other") or 0)
            output = int(tu.get("output") or 0)
            cache_read = int(tu.get("input_cache_read") or 0)
            cache_create = int(tu.get("input_cache_creation") or 0)
            total = input_other + output + cache_read + cache_create
            if total == 0:
                continue

            ts = parse_ts(obj.get("timestamp")) or parse_ts(payload.get("timestamp"))
            month = ts.strftime("%Y-%m") if ts else "unknown"

            for bucket in (totals, monthly[month]):
                bucket["inputTokens"] += input_other
                bucket["outputTokens"] += output
                bucket["cacheReadTokens"] += cache_read
                bucket["cacheCreationTokens"] += cache_create
                bucket["totalTokens"] += total


def main():
    totals = new_bucket()
    monthly = defaultdict(new_bucket)

    for path in session_files(KIMI_HOME):
        try:
            process_file(path, totals, monthly)
        except OSError:
            continue

    months = []
    for month in sorted(monthly):
        entry = {"month": month}
        entry.update(monthly[month])
        months.append(entry)

    json.dump({"totals": totals, "monthly": months}, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
