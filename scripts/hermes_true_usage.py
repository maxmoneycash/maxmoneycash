#!/usr/bin/env python3
"""Hermes gateway usage (the cloud swarm's 8th agent) → tokens.json schema.

The hermes-agent box runs the peat-ui swarm through the Hermes gateway
(OpenAI Codex OAuth), which does NOT write ~/.claude or ~/.codex session
logs — its token accounting lives only in /root/.hermes/**/state.db
`sessions` rows (per-session input/output/cache/reasoning counters,
started_at as epoch seconds). ccusage can't see any of it.

collect_cloud_tokens.sh dumps those rows to hermes-sessions.json and this
script folds them into data/hermes-cache.json keyed by profile:session-id,
keeping the LARGEST value seen per session (session counters only grow).
The committed cache is the durable record: the 2026-07-05 box rebuild
destroyed 16.4B tokens of raw logs, so cloud usage is never again trusted
to live only on the box. Pruned sessions and even a full box wipe cannot
shrink the cache.

Field mapping → tokens.json schema:
  inputTokens         = input_tokens
  outputTokens        = output_tokens + reasoning_tokens
  cacheReadTokens     = cache_read_tokens
  cacheCreationTokens = cache_write_tokens
Cost = 0 (subscription OAuth, no per-token price).

Usage:
  hermes_true_usage.py <hermes-sessions.json>   fold dump into cache, emit monthly
  hermes_true_usage.py                          emit from cache alone (box offline)
  hermes_true_usage.py <dump> --exclude-profile main
      fold every session into the durable cache, but omit a profile from this
      output when another collector source already includes it

Outputs {totals, monthly:[...]} (cursor/codex schema) to stdout.
"""
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "hermes-cache.json"
COMPONENTS = ["inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens"]


def load_cache():
    try:
        c = json.loads(CACHE.read_text())
        if isinstance(c.get("sessions"), dict):
            return c
    except Exception:
        pass
    return {"sessions": {}}


def month_of(started_at):
    try:
        return datetime.datetime.fromtimestamp(
            float(started_at), datetime.timezone.utc
        ).strftime("%Y-%m")
    except Exception:
        return "unknown"


def empty_month():
    bucket = {c: 0 for c in COMPONENTS}
    bucket.update({"totalTokens": 0, "totalCost": 0.0, "models": {}})
    return bucket


def empty_model():
    bucket = {c: 0 for c in COMPONENTS}
    bucket.update({"totalTokens": 0, "cost": 0.0})
    return bucket


def aggregate_sessions(sessions, excluded_profiles=None):
    """Aggregate the durable cache, optionally hiding already-counted profiles."""
    excluded_profiles = set(excluded_profiles or ())
    monthly = {}
    for key, entry in sessions.items():
        profile = key.split(":", 1)[0]
        if profile in excluded_profiles:
            continue
        m = monthly.setdefault(entry["month"], empty_month())
        model = entry.get("model") or "unknown"
        mm = m["models"].setdefault(model, empty_model())
        for c in COMPONENTS:
            value = entry.get(c, 0)
            m[c] += value
            mm[c] += value
            m["totalTokens"] += value
            mm["totalTokens"] += value

    out_monthly = [{"month": key, **value} for key, value in sorted(monthly.items())]
    totals = {c: sum(month[c] for month in out_monthly) for c in COMPONENTS}
    totals["totalTokens"] = sum(month["totalTokens"] for month in out_monthly)
    totals["totalCost"] = 0.0
    return totals, out_monthly


def profile_is_covered_by_ccusage(profile, rows, ccusage):
    """Prove that ccusage already contains a Hermes profile month by month.

    Hermes records reasoning separately while ccusage folds it into totalTokens,
    so outputTokens is compared without reasoning and totalTokens with it.
    Component-wise coverage also keeps this valid if direct cloud usage is added
    alongside the mirrored profile later.
    """
    profile_monthly = {}
    for row in rows:
        if (row.get("profile") or "main") != profile:
            continue
        month = month_of(row.get("started_at"))
        bucket = profile_monthly.setdefault(month, {c: 0 for c in COMPONENTS + ["totalTokens"]})
        values = {
            "inputTokens": row.get("input_tokens") or 0,
            "outputTokens": row.get("output_tokens") or 0,
            "cacheCreationTokens": row.get("cache_write_tokens") or 0,
            "cacheReadTokens": row.get("cache_read_tokens") or 0,
        }
        for component, value in values.items():
            bucket[component] += value
            bucket["totalTokens"] += value
        bucket["totalTokens"] += row.get("reasoning_tokens") or 0

    if not profile_monthly:
        return False
    ccusage_monthly = {row.get("period"): row for row in ccusage.get("monthly") or []}
    for month, expected in profile_monthly.items():
        observed = ccusage_monthly.get(month)
        if not observed:
            return False
        for component, value in expected.items():
            if (observed.get(component) or 0) < value:
                return False
    return True


def parse_output_args(args):
    dump_path = None
    excluded_profiles = set()
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--exclude-profile":
            index += 1
            if index >= len(args):
                raise SystemExit("--exclude-profile requires a profile name")
            excluded_profiles.add(args[index])
        elif dump_path is None:
            dump_path = arg
        else:
            raise SystemExit(f"unexpected argument: {arg}")
        index += 1
    return dump_path, excluded_profiles


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--profile-covered-by-ccusage":
        if len(sys.argv) != 5:
            raise SystemExit(
                "usage: hermes_true_usage.py --profile-covered-by-ccusage "
                "<profile> <ccusage-monthly.json> <hermes-sessions.json>"
            )
        profile, ccusage_path, dump_path = sys.argv[2:]
        ccusage = json.loads(pathlib.Path(ccusage_path).read_text())
        rows = json.loads(pathlib.Path(dump_path).read_text())
        raise SystemExit(0 if profile_is_covered_by_ccusage(profile, rows, ccusage) else 1)

    dump_path, excluded_profiles = parse_output_args(sys.argv[1:])
    cache = load_cache()
    sessions = cache["sessions"]

    if dump_path:
        dump = json.loads(pathlib.Path(dump_path).read_text())
        for row in dump:
            key = f"{row.get('profile', 'main')}:{row['id']}"
            entry = {
                "month": month_of(row.get("started_at")),
                "model": row.get("model") or "unknown",
                "inputTokens": row.get("input_tokens") or 0,
                "outputTokens": (row.get("output_tokens") or 0)
                + (row.get("reasoning_tokens") or 0),
                "cacheCreationTokens": row.get("cache_write_tokens") or 0,
                "cacheReadTokens": row.get("cache_read_tokens") or 0,
            }
            if sum(entry[c] for c in COMPONENTS) == 0:
                continue
            old = sessions.get(key)
            # session counters only grow; keep the largest snapshot ever seen
            if old is None or sum(entry[c] for c in COMPONENTS) >= sum(
                old.get(c, 0) for c in COMPONENTS
            ):
                sessions[key] = entry
        CACHE.write_text(json.dumps(cache, sort_keys=True))

    totals, out_monthly = aggregate_sessions(sessions, excluded_profiles)
    generated = (datetime.datetime.now(datetime.timezone.utc)
                 .isoformat(timespec="seconds").replace("+00:00", "Z"))
    json.dump({
        "totals": totals,
        "monthly": out_monthly,
        "generated_at": generated,
        "excludedProfiles": sorted(excluded_profiles),
    }, sys.stdout)


if __name__ == "__main__":
    main()
