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
  hermes_true_usage.py <dump> --exclude-covered-dump-profile main <ccusage.json>
      fold every session into the durable cache, then omit only the current
      dump's profile sessions that ccusage proves it already includes. Older
      cached sessions stay visible even if the box prunes them.

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


def aggregate_sessions(sessions, excluded_profiles=None, excluded_keys=None):
    """Aggregate cache, optionally hiding already-counted profiles or sessions."""
    excluded_profiles = set(excluded_profiles or ())
    excluded_keys = set(excluded_keys or ())
    monthly = {}
    for key, entry in sessions.items():
        profile = key.split(":", 1)[0]
        if profile in excluded_profiles or key in excluded_keys:
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


def session_keys_are_covered_by_ccusage(sessions, keys, ccusage):
    """Prove that ccusage covers selected durable Hermes sessions by month.

    The cache folds reasoning into outputTokens while ccusage exposes reasoning
    only through totalTokens. Compare the other components plus totalTokens so
    the proof remains valid for both old cache entries and fresh dump rows.
    """
    selected_monthly = {}
    for key in keys:
        entry = sessions.get(key)
        if not entry:
            continue
        month = entry["month"]
        bucket = selected_monthly.setdefault(month, {
            "inputTokens": 0,
            "cacheCreationTokens": 0,
            "cacheReadTokens": 0,
            "totalTokens": 0,
        })
        for component in ("inputTokens", "cacheCreationTokens", "cacheReadTokens"):
            value = entry.get(component, 0)
            bucket[component] += value
        bucket["totalTokens"] += sum(entry.get(component, 0) for component in COMPONENTS)

    if not selected_monthly:
        return False
    ccusage_monthly = {row.get("period"): row for row in ccusage.get("monthly") or []}
    for month, expected in selected_monthly.items():
        observed = ccusage_monthly.get(month)
        if not observed:
            return False
        for component, value in expected.items():
            if (observed.get(component) or 0) < value:
                return False
    return True


def entry_from_row(row):
    return {
        "month": month_of(row.get("started_at")),
        "model": row.get("model") or "unknown",
        "inputTokens": row.get("input_tokens") or 0,
        "outputTokens": (row.get("output_tokens") or 0)
        + (row.get("reasoning_tokens") or 0),
        "cacheCreationTokens": row.get("cache_write_tokens") or 0,
        "cacheReadTokens": row.get("cache_read_tokens") or 0,
    }


def fold_rows(sessions, rows):
    """Fold a dump into the durable cache and return its non-empty session keys."""
    dump_keys = set()
    for row in rows:
        key = f"{row.get('profile', 'main')}:{row['id']}"
        entry = entry_from_row(row)
        if sum(entry[c] for c in COMPONENTS) == 0:
            continue
        dump_keys.add(key)
        old = sessions.get(key)
        # Session counters only grow; keep the largest snapshot ever seen.
        if old is None or sum(entry[c] for c in COMPONENTS) >= sum(
            old.get(c, 0) for c in COMPONENTS
        ):
            sessions[key] = entry
    return dump_keys


def profile_is_covered_by_ccusage(profile, rows, ccusage):
    """Compatibility helper: prove coverage for a profile in one dump."""
    sessions = {}
    dump_keys = fold_rows(sessions, rows)
    profile_keys = {
        key for key in dump_keys if key.split(":", 1)[0] == profile
    }
    return session_keys_are_covered_by_ccusage(sessions, profile_keys, ccusage)


def parse_output_args(args):
    dump_path = None
    covered_dump_profiles = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--exclude-covered-dump-profile":
            if index + 2 >= len(args):
                raise SystemExit(
                    "--exclude-covered-dump-profile requires a profile and ccusage file"
                )
            covered_dump_profiles.append((args[index + 1], args[index + 2]))
            index += 2
        elif dump_path is None:
            dump_path = arg
        else:
            raise SystemExit(f"unexpected argument: {arg}")
        index += 1
    return dump_path, covered_dump_profiles


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
        sessions = load_cache()["sessions"]
        dump_keys = fold_rows(sessions, rows)
        profile_keys = {
            key for key in dump_keys if key.split(":", 1)[0] == profile
        }
        raise SystemExit(
            0 if session_keys_are_covered_by_ccusage(
                sessions, profile_keys, ccusage
            ) else 1
        )

    dump_path, covered_dump_profiles = parse_output_args(sys.argv[1:])
    cache = load_cache()
    sessions = cache["sessions"]
    dump_keys = set()

    if dump_path:
        dump = json.loads(pathlib.Path(dump_path).read_text())
        dump_keys = fold_rows(sessions, dump)
        CACHE.write_text(json.dumps(cache, sort_keys=True))

    excluded_keys = set()
    covered_profiles = []
    for profile, ccusage_path in covered_dump_profiles:
        profile_keys = {
            key for key in dump_keys if key.split(":", 1)[0] == profile
        }
        ccusage = json.loads(pathlib.Path(ccusage_path).read_text())
        if session_keys_are_covered_by_ccusage(
            sessions, profile_keys, ccusage
        ):
            excluded_keys.update(profile_keys)
            covered_profiles.append(profile)

    totals, out_monthly = aggregate_sessions(sessions, excluded_keys=excluded_keys)
    generated = (datetime.datetime.now(datetime.timezone.utc)
                 .isoformat(timespec="seconds").replace("+00:00", "Z"))
    json.dump({
        "totals": totals,
        "monthly": out_monthly,
        "generated_at": generated,
        "excludedProfiles": sorted(set(covered_profiles)),
        "excludedSessionCount": len(excluded_keys),
    }, sys.stdout)


if __name__ == "__main__":
    main()
