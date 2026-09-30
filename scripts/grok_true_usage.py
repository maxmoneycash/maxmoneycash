"""Grok Build (xAI `grok` CLI) usage — parsed from ~/.grok/logs/unified.jsonl.

Grok logs one `shell.turn.inference_done` line per inference with a ctx of
prompt_tokens / cached_prompt_tokens / completion_tokens / reasoning_tokens.
Active and retained rotated logs can overlap or reappear. We accumulate into
data/grok-cache.json while retaining every accepted inference ID. At the bounded
cache capacity we hold collection instead of evicting identities or history.
Legacy caches that may already have evicted IDs require separate reconciliation.

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
import contextlib
import copy
import datetime
import fcntl
import glob
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "grok-cache.json"
GROK_HOME = pathlib.Path(os.environ.get("GROK_HOME", pathlib.Path.home() / ".grok"))
UNKNOWN_MODEL = "unknown"
CACHE_VERSION = 3
COMPONENTS = ["inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens"]
LEGACY_SEEN_CAP = 100_000
# Resource limits, never rolling retention windows. Exhaustion holds the prior
# cache/publication and needs a separately reviewed storage migration.
MAX_SEEN_IDS = 1_000_000
MAX_CACHE_BYTES = 64 * 1024 * 1024
MAX_ID_BYTES = 512


class CollectionHeld(RuntimeError):
    """Fixed reason codes: never expose event IDs, file paths or raw records."""


def held(reason):
    raise CollectionHeld(reason)


def empty_month():
    return {"inputTokens": 0, "outputTokens": 0, "cacheCreationTokens": 0,
            "cacheReadTokens": 0, "totalTokens": 0, "calls": 0, "models": {}}


def empty_model():
    return {"inputTokens": 0, "outputTokens": 0, "cacheCreationTokens": 0,
            "cacheReadTokens": 0, "totalTokens": 0}


def token_vector(value):
    if type(value) is not dict:
        held("invalid_counters")
    counts = []
    for key in COMPONENTS + ["totalTokens"]:
        count = value.get(key)
        if type(count) is not int or count < 0:
            held("invalid_counters")
        counts.append(count)
    if sum(counts[:-1]) != counts[-1]:
        held("inconsistent_counters")
    return counts


def valid_identity(value):
    if type(value) is not str or not value or any(ord(char) < 32 for char in value):
        held("invalid_identity")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        held("invalid_identity")
    if size > MAX_ID_BYTES:
        held("invalid_identity")


def validate_cache(cache):
    if type(cache) is not dict or set(cache) - {"version", "monthly", "seen"}:
        held("invalid_cache")
    version = cache.get("version", 1)
    if type(version) is not int or version not in (1, 2, CACHE_VERSION):
        held("unsupported_cache_version")
    monthly, seen = cache.get("monthly"), cache.get("seen")
    if type(monthly) is not dict or type(seen) is not list:
        held("invalid_cache")
    if len(seen) > MAX_SEEN_IDS:
        held("identity_capacity")
    for identity in seen:
        valid_identity(identity)
    if len(set(seen)) != len(seen):
        held("duplicate_cached_identity")
    calls = 0
    for period, month in monthly.items():
        if type(period) is not str or not period or type(month) is not dict:
            held("invalid_month")
        vector = token_vector(month)
        count = month.get("calls")
        if type(count) is not int or count < 0:
            held("unknown_identity_coverage")
        if count == 0 and any(vector):
            held("unknown_identity_coverage")
        calls += count
        if version >= 2:
            models = month.get("models")
            if type(models) is not dict:
                held("invalid_models")
            vectors = []
            for name, usage in models.items():
                valid_identity(name)
                vectors.append(token_vector(usage))
            if [sum(row[i] for row in vectors) for i in range(5)] != vector:
                held("inconsistent_models")
    # Existing writers incremented calls and appended one ID together, never
    # shortened a sub-cap list. At the old cap we cannot distinguish a complete
    # cache from an evicted one. Aggregate values cannot recover those IDs.
    if calls != len(seen) or (version < CACHE_VERSION and len(seen) >= LEGACY_SEEN_CAP):
        held("unknown_identity_coverage")
    return cache


def load_cache():
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                held("duplicate_cache_key")
            result[key] = value
        return result
    try:
        with CACHE.open("rb") as file:
            raw = file.read(MAX_CACHE_BYTES + 1)
    except FileNotFoundError:
        return {"version": CACHE_VERSION, "monthly": {}, "seen": []}
    if len(raw) > MAX_CACHE_BYTES:
        held("cache_byte_capacity")
    try:
        cache = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        held("invalid_cache_json")
    return validate_cache(cache)


@contextlib.contextmanager
def cache_lock():
    """Atomic replacement needs a separate stable lock inode for direct callers."""
    CACHE.parent.mkdir(exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(CACHE.with_name(CACHE.name + ".lock"), flags, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            held("concurrent_cache_writer")
        if CACHE.is_symlink():
            held("unsupported_cache_symlink")
        yield
    finally:
        os.close(fd)


def encode_cache(cache):
    validate_cache(cache)
    try:
        encoded = json.dumps(cache, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        held("cache_serialization_failed")
    if len(encoded) > MAX_CACHE_BYTES:
        held("cache_byte_capacity")
    return encoded


def save_cache(cache):
    encoded = encode_cache(cache)
    if CACHE.exists() and CACHE.read_bytes() == encoded:
        return
    # Monthly counters and their full identity set commit in the same file.
    # A failed write/replace leaves the prior complete bytes intact.
    fd, temporary = tempfile.mkstemp(prefix=".grok-cache-", dir=CACHE.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, CACHE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def model_timelines():
    timelines = {}
    pattern = str(GROK_HOME / "sessions" / "**" / "events.jsonl")
    for fp in sorted(glob.glob(pattern, recursive=True)):
        with open(fp, errors="ignore") as file:
            for line in file:
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
        with open(fp, errors="ignore") as file:
            for line in file:
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
                if len(seen_in_logs) > MAX_SEEN_IDS:
                    held("input_identity_capacity")
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


def accumulate_cache(original, records):
    """Pure candidate; malformed/capacity failures never mutate the caller."""
    validate_cache(original)
    if type(records) is not list or len(records) > MAX_SEEN_IDS:
        held("invalid_record_batch")
    cache = copy.deepcopy(original)
    monthly = cache["monthly"]
    seen = set(cache["seen"])
    new_ids = []
    for record in records:
        if type(record) is not dict or set(record) != {"id", "month", "model", "usage"}:
            held("invalid_record")
        valid_identity(record["id"])
        valid_identity(record["month"])
        valid_identity(record["model"])
        token_vector(record["usage"])
    if cache.get("version", 1) < 2:
        migrate_legacy_months(monthly, records, seen)
    for record in records:
        if record["id"] in seen:
            continue
        if len(seen) >= MAX_SEEN_IDS:
            held("identity_capacity")
        seen.add(record["id"])
        new_ids.append(record["id"])
        month = monthly.setdefault(record["month"], empty_month())
        add_usage(month, record["usage"])
        model = month.setdefault("models", {}).setdefault(
            record["model"], empty_model())
        add_usage(model, record["usage"])
        month["calls"] = month.get("calls", 0) + 1

    candidate = {"version": CACHE_VERSION, "monthly": monthly, "seen": cache["seen"] + new_ids}
    encode_cache(candidate)  # Admission includes encoded-byte capacity before returning.
    return candidate


def main():
    with cache_lock():
        cache = load_cache()
        records = usage_records(model_timelines())
        candidate = accumulate_cache(cache, records)
        save_cache(candidate)
    monthly = candidate["monthly"]

    # build output in the cursor/codex monthly schema
    out_monthly = []
    for month in sorted(monthly):
        m = monthly[month]
        out_monthly.append({
            "month": month,
            "inputTokens": m["inputTokens"], "outputTokens": m["outputTokens"],
            "cacheCreationTokens": m["cacheCreationTokens"], "cacheReadTokens": m["cacheReadTokens"],
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
    try:
        main()
    except (CollectionHeld, OSError) as error:
        reason = str(error) if isinstance(error, CollectionHeld) else "cache_or_source_io"
        print(f"Grok collection held: {reason}; prior cache retained", file=sys.stderr)
        raise SystemExit(1)
