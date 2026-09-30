"""Pure proposed Grok ownership; never discovers, persists or publishes data.

Caller declarations and unsigned continuations are evidence, not authenticity or
lifetime certification. Any unresolved identity holds the entire proposal.
"""
import copy
import datetime as dt
import hashlib
import json
import re

from grok_true_usage import CollectionHeld, COMPONENTS, encode_cache

PROTOCOL = "grok-owner-proposal-v1"
MAX_RECORDS = 100_000
MAX_BYTES = 64 * 1024 * 1024
U64 = (1 << 64) - 1
UNKNOWN = "unknown"
FIELDS = COMPONENTS + ["totalTokens"]
STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})\Z", re.ASCII)
DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)\Z", re.ASCII)


class OwnershipHeld(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise OwnershipHeld(reason)


def keys(value, required, optional=()):
    require(type(value) is dict and set(required) <= set(value)
            and set(value) <= set(required) | set(optional), "unsupported_shape")


def text(value):
    require(type(value) is str and 0 < len(value) <= 512, "invalid_text")
    require(all(32 <= ord(c) < 127 for c in value), "unsupported_text")
    return value


def uint(value):
    require(type(value) is int and 0 <= value <= U64, "invalid_counter")
    return value


def encoded(value):
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise OwnershipHeld("invalid_json_value") from None
    require(len(data) <= MAX_BYTES, "byte_capacity")
    return data


def instant(timestamp):
    """Preserve up to nanosecond precision; never dedup by rounded milliseconds."""
    text(timestamp)
    match = STAMP.fullmatch(timestamp)
    require(match is not None, "unsupported_timestamp")
    day, clock, fraction, offset = match.groups()
    require(offset != "-00:00", "unknown_timestamp_offset")
    require(offset == "Z" or (int(offset[1:3]) <= 23 and int(offset[4:]) <= 59), "unsupported_timestamp")
    try:
        zone = "+00:00" if offset == "Z" else offset
        utc = dt.datetime.fromisoformat(day + "T" + clock + zone).astimezone(dt.timezone.utc)
    except (ValueError, OverflowError):
        raise OwnershipHeld("unsupported_timestamp") from None
    day = f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}"
    return day + utc.strftime("T%H:%M:%S") + "." + (fraction or "").ljust(9, "0") + "Z"


def identity(source, session, timestamp, loop):
    text(session)
    require("|" not in session and ":" not in session, "ambiguous_session_identity")
    return (source, session, instant(timestamp), uint(loop))


def legacy_identity(source, key):
    text(key)
    parts = key.split("|")
    require(len(parts) == 4, "unknown_legacy_identity")
    session, timestamp, loop, prompt = parts
    require(DECIMAL.fullmatch(loop) is not None and DECIMAL.fullmatch(prompt) is not None,
            "unknown_legacy_identity")
    prompt = uint(int(prompt))
    return identity(source, session, timestamp, int(loop)), timestamp[:7], prompt


def validate_scope(scope):
    keys(scope, {"sourceID", "legacySourceID", "nativeSourceIDs", "sideSourceIDs",
                 "captureComplete", "legacyIdentityCoverage", "timezone"})
    source = text(scope["sourceID"])
    require(scope["legacySourceID"] == source and scope["nativeSourceIDs"] == [source]
            and scope["sideSourceIDs"] == [source], "uncertain_source_scope")
    require(scope["captureComplete"] is True and scope["legacyIdentityCoverage"] == "complete"
            and scope["timezone"] == "UTC", "incomplete_declared_coverage")
    return source


def parse_record(envelope, source):
    keys(envelope, {"sourceID", "origin", "nativeModel", "ownerModel", "record"})
    require(envelope["sourceID"] == source and envelope["origin"] in ("active", "rotated"),
            "uncertain_record_scope")
    native_model, owner_model = text(envelope["nativeModel"]), text(envelope["ownerModel"])
    require(owner_model == UNKNOWN or owner_model == native_model, "conflicting_model_evidence")
    raw = envelope["record"]
    keys(raw, {"ts", "sid", "msg", "ctx"}, {"src"})
    require(raw["msg"] == "shell.turn.inference_done", "unsupported_record_kind")
    if "src" in raw:
        text(raw["src"])
    ctx = raw["ctx"]
    keys(ctx, {"loop_index"}, {"prompt_tokens", "cached_prompt_tokens", "completion_tokens", "reasoning_tokens"})
    key = identity(source, raw["sid"], raw["ts"], ctx["loop_index"])
    prompt = uint(ctx.get("prompt_tokens", 0))
    cached = uint(ctx.get("cached_prompt_tokens", 0))
    completion, reasoning = uint(ctx.get("completion_tokens", 0)), uint(ctx.get("reasoning_tokens", 0))
    total = uint(prompt + completion + reasoning)
    require(total > 0, "nonpositive_inference")
    cache_read = min(cached, prompt)
    side_key = (f'{raw["sid"]}|{raw["ts"]}|{ctx["loop_index"]}|{prompt}'
                if "prompt_tokens" in ctx else None)
    native_key = f'{raw["sid"]}:{raw["ts"]}:{prompt-cache_read}:{completion}:{cache_read}:{reasoning}:{native_model}'
    event = {"identity": {"sourceID": source, "sessionID": raw["sid"], "instantUTC": key[2], "loopIndex": key[3]},
             "timestampText": raw["ts"], "sideKey": side_key, "nativeKey": native_key,
             "nativeModel": native_model, "ownerModel": owner_model, "utcMonth": key[2][:7],
             "payload": {"promptTokens": prompt if "prompt_tokens" in ctx else None,
                         "cachedPromptTokens": cached, "completionTokens": completion, "reasoningTokens": reasoning},
             "usage": {"inputTokens": prompt-cache_read, "outputTokens": completion+reasoning,
                       "cacheCreationTokens": 0, "cacheReadTokens": cache_read, "totalTokens": total}}
    return key, event


def add_usage(target, usage):
    for field in FIELDS:
        target[field] = uint(target.get(field, 0) + usage[field])


def empty_usage():
    return dict.fromkeys(FIELDS, 0)


def _classify(legacy_cache, records, scope, continuation):
    source = validate_scope(scope)
    # Reuse the reviewed cache admission rule, including old-cap uncertainty.
    baseline_bytes = encode_cache(legacy_cache)
    require(len(baseline_bytes) <= MAX_BYTES, "byte_capacity")
    baseline_hash = hashlib.sha256(baseline_bytes).hexdigest()
    require(type(records) is list and len(records) <= MAX_RECORDS, "record_capacity")
    previous = []
    if continuation is not None:
        keys(continuation, {"protocol", "scope", "baselineSHA256", "admittedRecords"})
        require(continuation["protocol"] == PROTOCOL and continuation["scope"] == scope
                and continuation["baselineSHA256"] == baseline_hash, "continuation_boundary_changed")
        previous = continuation["admittedRecords"]
        require(type(previous) is list and len(previous) <= MAX_RECORDS, "record_capacity")
    require(len(previous) + len(records) <= MAX_RECORDS, "record_capacity")
    encoded({"legacy": legacy_cache, "records": records, "scope": scope, "previous": previous})
    legacy_by_identity, legacy_instants, period_proof = {}, set(), {}
    for side_key in legacy_cache["seen"]:
        key, old_period, prompt = legacy_identity(source, side_key)
        require(key not in legacy_by_identity, "legacy_identity_alias")
        legacy_by_identity[key] = side_key
        legacy_instants.add(key[:3])
        count, prompts = period_proof.get(old_period, (0, 0))
        period_proof[old_period] = (count + 1, uint(prompts + prompt))
    require(set(period_proof) <= set(legacy_cache["monthly"]), "legacy_period_coverage")
    for period, month in legacy_cache["monthly"].items():
        count, prompts = period_proof.get(period, (0, 0))
        require(count == month["calls"] and prompts == month["inputTokens"] + month["cacheReadTokens"],
                "legacy_period_coverage")

    events, native_identities, witnesses, retained = {}, {}, {}, set()
    for is_previous, batch in [(True, previous), (False, records)]:
        for envelope in batch:
            key, event = parse_record(envelope, source)
            # Neither producer key may silently collapse distinct evidence.
            old_key = native_identities.get(event["nativeKey"])
            require(old_key is None or old_key == key, "native_key_collision")
            native_identities[event["nativeKey"]] = key
            if key in events:
                require(events[key]["timestampText"] == event["timestampText"], "timestamp_alias")
                require(events[key]["payload"] == event["payload"], "changed_payload")
                require(events[key] == event, "conflicting_model_evidence")
            else:
                events[key] = event
            witnesses.setdefault(key, {})[envelope["origin"]] = copy.deepcopy(envelope)
            if is_previous:
                retained.add(key)

    # Preserve every legacy month/model/component unchanged in the baseline.
    # Additional rows are separate; no inference about old dates/model attribution.
    additions, evidence, admitted_records = {}, [], []
    added_now = empty_usage()
    retained_usage = empty_usage()
    for key, event in sorted(events.items()):
        legacy_key = legacy_by_identity.get(key)
        if legacy_key is not None:
            require(event["sideKey"] == legacy_key, "legacy_record_alias")
            require(key not in retained, "continuation_overlaps_baseline")
            disposition = "covered"
        else:
            # Native batch identity omits loop. The old cache has no per-event
            # completion/reasoning/model payload, so a new loop at a retained
            # source/session/instant may still be the same native event. A
            # current old-loop witness cannot authenticate that missing past
            # payload. Preserve the baseline and hold this whole proposal.
            require(key[:3] not in legacy_instants, "legacy_loop_overlap_unknown")
            disposition = "retained" if key in retained else "new"
            add_usage(retained_usage if key in retained else added_now, event["usage"])
            month = additions.setdefault(event["utcMonth"], {**empty_usage(), "calls": 0, "models": {}})
            add_usage(month, event["usage"])
            month["calls"] += 1
            add_usage(month["models"].setdefault(event["ownerModel"], empty_usage()), event["usage"])
            for origin in sorted(witnesses[key]):
                admitted_records.append(witnesses[key][origin])
        evidence.append({**event, "origins": sorted(witnesses[key]), "disposition": disposition})

    baseline_totals = empty_usage()
    for month in legacy_cache["monthly"].values():
        add_usage(baseline_totals, month)
    totals = dict(baseline_totals)
    for month in additions.values():
        add_usage(totals, month)
    result = {"protocol": PROTOCOL, "status": "proposed", "publicationAllowed": False,
              "lifetimeCertified": False, "scope": copy.deepcopy(scope), "baselineSHA256": baseline_hash,
              "baseline": copy.deepcopy(legacy_cache), "baselineTotals": baseline_totals,
              "additionalMonthly": additions, "proposedTotals": totals,
              "newUsage": added_now, "retainedUsage": retained_usage, "events": evidence,
              "continuation": {"protocol": PROTOCOL, "scope": copy.deepcopy(scope),
                               "baselineSHA256": baseline_hash, "admittedRecords": admitted_records}}
    encoded(result)
    return result


def classify_owner(legacy_cache, records, scope, continuation=None):
    """Return an unsigned proposal or a fixed held reason; never mutate inputs.

    A held result has no candidate counters/continuation. The caller retains all
    supplied evidence unchanged. Reuse continuation with the exact same legacy
    baseline/scope to retain newly proposed events through replay/raw rotation.
    Coverage/source/model statements are caller declarations, not verified here.
    """
    try:
        return _classify(legacy_cache, records, scope, continuation)
    except (OwnershipHeld, CollectionHeld) as error:
        return {"protocol": PROTOCOL, "status": "held", "reason": str(error),
                "publicationAllowed": False, "lifetimeCertified": False}
