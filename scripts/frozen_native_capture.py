"""Pure admission/splitting of ONE supplied native UTC report, with no I/O.

This is an unwired migration building block, not a collector or publisher.
An internally consistent report is not proof that readers found every event.
Side ledgers are described, never added, subtracted, or assigned ownership.
See frozen_native_capture.md for the versioned input/output contract.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, DecimalException, localcontext
import hashlib
import json
import re


COMPONENTS = ("inputTokens", "outputTokens", "cacheReadTokens", "cacheCreationTokens")
COUNTERS = (*COMPONENTS, "totalTokens")
MAX_COUNTER = 2**64 - 1
MAX_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_DAYS = 40_000
MAX_MONTHS = 1_200
MAX_PROVIDERS = 256
MAX_MODELS = 4_096
MAX_MODEL_ROWS = 100_000
BASE_FIELDS = {*COUNTERS, "totalCost", "modelsUsed", "modelBreakdowns", "agent"}
RECEIPT_FIELDS = {
    "protocol", "sourceID", "scannerVersion", "scannerSHA256", "startedAt", "endedAt",
    "timezone", "command", "sections", "allHistory", "offline", "byAgent", "processExitCode",
}


class CaptureRejected(ValueError):
    """Fixed diagnostics contain structural paths, never source names/values."""

    def __init__(self, code, path):
        self.code, self.path = code, path
        super().__init__(f"{code} at {path}")


def reject(code, path):
    raise CaptureRejected(code, path)


def exact_keys(value, keys, path):
    if type(value) is not dict or set(value) != keys:
        reject("unexpected_shape", path)


def count(value, path):
    if type(value) is not int or not 0 <= value <= MAX_COUNTER:
        reject("invalid_counter", path)
    return value


def identity(value, path):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
        reject("invalid_identity", path)
    return value


def model_name(value, path):
    if type(value) is not str or not 1 <= len(value) <= 256 or any(ord(c) < 32 or ord(c) > 126 for c in value):
        reject("invalid_model", path)
    return value


def money(value, path):
    if type(value) not in (int, Decimal):
        reject("invalid_cost", path)
    value = Decimal(value)
    if (not value.is_finite() or len(value.as_tuple().digits) > 128
            or abs(value.as_tuple().exponent) > 128 or not 0 <= value <= Decimal("1e18")):
        reject("invalid_cost", path)
    return value


def money_text(value):
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def day(value, path):
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        reject("invalid_period", path)
    try:
        return date.fromisoformat(value)
    except ValueError:
        reject("invalid_period", path)


def instant(value, path):
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z", value):
        reject("invalid_time", path)
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        reject("invalid_time", path)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


@dataclass(frozen=True)
class FrozenCapture:
    """Immutable normalized bytes; callers get a new mutable view on demand."""

    encoded: bytes

    def as_dict(self):
        return json.loads(self.encoded)


def _receipt(value):
    exact_keys(value, RECEIPT_FIELDS, "receipt")
    identity(value["sourceID"], "receipt.sourceID")
    if type(value["scannerVersion"]) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._+-]{0,95}", value["scannerVersion"]):
        reject("invalid_version", "receipt.scannerVersion")
    if type(value["scannerSHA256"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", value["scannerSHA256"]):
        reject("invalid_hash", "receipt.scannerSHA256")
    start, end = instant(value["startedAt"], "receipt.startedAt"), instant(value["endedAt"], "receipt.endedAt")
    if end < start:
        reject("reversed_time", "receipt.endedAt")
    if (value["protocol"] != "turbotokens-multisection-v1" or value["timezone"] != "UTC"
            or value["command"] != "monthly" or value["sections"] != ["daily", "monthly"]
            or value["allHistory"] is not True or value["offline"] is not True or value["byAgent"] is not True
            or type(value["processExitCode"]) is not int or value["processExitCode"] != 0):
        reject("unsupported_capture_scope", "receipt")
    return {**value, "sections": list(value["sections"])}, end.date()


def _decode(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        reject("invalid_body_size_or_type", "report")

    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                reject("duplicate_key", "report")
            result[key] = value
        return result

    def constant(_):
        reject("nonfinite_number", "report")

    def decimal_number(literal):
        if len(literal) > 256:
            reject("invalid_number", "report")
        try:
            return Decimal(literal)
        except DecimalException:
            reject("invalid_number", "report")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=decimal_number, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        if isinstance(error, CaptureRejected):
            raise
        reject("invalid_json", "report")
    exact_keys(value, {"monthly", "daily", "totals"}, "report")
    return value


def _token_vector(row, path):
    result = {key: count(row.get(key), f"{path}.{key}") for key in COUNTERS}
    if sum(result[key] for key in COMPONENTS) > result["totalTokens"]:
        reject("component_overallocation", path)
    return result


def _sum_vectors(rows, path):
    return {key: count(sum(row[key] for row in rows), f"{path}.{key}") for key in COUNTERS}


def _models(rows):
    """Only token vectors are compared: serialized float cost sums can differ."""
    result = {}
    for row in rows:
        for model in row["models"]:
            vector = result.setdefault(model["modelName"], dict.fromkeys(COMPONENTS, 0))
            for key in COMPONENTS:
                vector[key] += model[key]
    return result


def _check_fold(parent, children, path):
    if _sum_vectors(children, path) != {key: parent[key] for key in COUNTERS}:
        reject("token_conservation", path)
    if _models([parent]) != _models(children):
        reject("model_conservation", path)
    if set(parent["modelsUsed"]) != {name for row in children for name in row["modelsUsed"]}:
        reject("model_scope_mismatch", path)


def _row(value, path, model_budget, *, period=False):
    exact_keys(value, BASE_FIELDS | ({"period", "metadata", "agents"} if period else set()), path)
    name = identity(value["agent"], f"{path}.agent")
    if (period and name != "all") or (not period and name == "all"):
        reject("invalid_provider_role", f"{path}.agent")
    tokens = _token_vector(value, path)
    names = value["modelsUsed"]
    if type(names) is not list or len(names) > MAX_MODELS:
        reject("invalid_models", f"{path}.modelsUsed")
    for item in names:
        model_name(item, f"{path}.modelsUsed")
    if len(set(names)) != len(names):
        reject("duplicate_model", f"{path}.modelsUsed")
    models = value["modelBreakdowns"]
    if type(models) is not list or len(models) > MAX_MODELS:
        reject("invalid_models", f"{path}.modelBreakdowns")
    model_budget[0] += len(models)
    if model_budget[0] > MAX_MODEL_ROWS:
        reject("capacity", "report.modelBreakdowns")
    admitted, seen = [], set()
    for i, model in enumerate(models):
        model_path = f"{path}.modelBreakdowns[{i}]"
        exact_keys(model, {*COMPONENTS, "modelName", "cost"}, model_path)
        model_id = model_name(model["modelName"], f"{model_path}.modelName")
        if model_id in seen or model_id not in names:
            reject("duplicate_or_undeclared_model", model_path)
        seen.add(model_id)
        admitted.append({"modelName": model_id,
                         **{key: count(model[key], f"{model_path}.{key}") for key in COMPONENTS},
                         "reportedCostUsd": money(model["cost"], f"{model_path}.cost")})
    for key in COMPONENTS:
        if sum(model[key] for model in admitted) > tokens[key]:
            reject("model_overallocation", f"{path}.modelBreakdowns")
    return {"provider": name, **tokens, "modelsUsed": sorted(names),
            "models": sorted(admitted, key=lambda model: model["modelName"]),
            "reportedCostUsd": money(value["totalCost"], f"{path}.totalCost")}


def _section(value, kind, last_day, budget):
    if type(value) is not list or len(value) > (MAX_MONTHS if kind == "monthly" else MAX_DAYS):
        reject("invalid_section_or_capacity", f"report.{kind}")
    result = {}
    for i, original in enumerate(value):
        path = f"report.{kind}[{i}]"
        row = _row(original, path, budget, period=True)
        period = original["period"]
        if kind == "monthly":
            if type(period) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", period):
                reject("invalid_period", f"{path}.period")
            first = day(period + "-01", f"{path}.period")
        else:
            first = day(period, f"{path}.period")
        if first > last_day or period in result:
            reject("future_or_duplicate_period", f"{path}.period")
        exact_keys(original["metadata"], {"agents"}, f"{path}.metadata")
        declared = original["metadata"]["agents"]
        if type(declared) is not list or len(declared) > MAX_PROVIDERS:
            reject("invalid_provider_scope", f"{path}.metadata.agents")
        for item in declared:
            identity(item, f"{path}.metadata.agents")
        agents = original["agents"]
        if type(agents) is not list or len(agents) > MAX_PROVIDERS:
            reject("invalid_providers", f"{path}.agents")
        children = {}
        for j, agent in enumerate(agents):
            child = _row(agent, f"{path}.agents[{j}]", budget)
            if child["provider"] in children:
                reject("duplicate_provider", f"{path}.agents")
            children[child["provider"]] = child
        if len(set(declared)) != len(declared) or set(declared) != set(children):
            reject("provider_scope_mismatch", f"{path}.metadata.agents")
        _check_fold(row, list(children.values()), path)
        result[period] = {**row, "period": period, "children": children}
    return result


def _ownership(providers, source_id, side_sources):
    if type(side_sources) not in (list, tuple) or len(side_sources) > MAX_PROVIDERS:
        reject("invalid_side_sources", "sideSources")
    sides, seen = {}, {source_id}
    for i, side in enumerate(side_sources):
        path = f"sideSources[{i}]"
        exact_keys(side, {"sourceID", "provider"}, path)
        sid, provider = identity(side["sourceID"], f"{path}.sourceID"), identity(side["provider"], f"{path}.provider")
        if sid in seen or provider == "all":
            reject("duplicate_or_invalid_source", path)
        seen.add(sid)
        sides.setdefault(provider, []).append(sid)
    return {"inventoryCompleteness": "unknown", "publicationAllowed": False,
            "providers": [{"provider": name, "nativeSourceID": source_id if name in providers else None,
                           "sideSourceIDs": sorted(sides.get(name, [])), "additiveOwner": None,
                           "status": "unresolved-native-side-overlap" if name in providers and name in sides
                           else "unresolved-side-history" if name in sides else "native-observation-only"}
                          for name in sorted(set(providers) | set(sides))]}


def _public_row(row, period=None):
    result = {key: str(row[key]) for key in COUNTERS}
    result.update({"modelsUsed": row["modelsUsed"], "reportedCostUsd": money_text(row["reportedCostUsd"]),
                   "unclassifiedComponentTokens": str(row["totalTokens"] - sum(row[key] for key in COMPONENTS)),
                   "unallocatedModelTokens": str(row["totalTokens"] - sum(model[key] for model in row["models"] for key in COMPONENTS)),
                   "modelBreakdowns": [{"modelName": model["modelName"],
                                         **{key: str(model[key]) for key in COMPONENTS},
                                         "reportedCostUsd": money_text(model["reportedCostUsd"])} for model in row["models"]]})
    if period is not None:
        result["period"] = period
    return result


def split_native_capture(report_bytes, *, receipt, daily_since=None, side_sources=()):
    """Validate fully before returning immutable bytes. Does not read or write.

    Counts use decimal strings in output, preserving the scanner's uint64 range.
    `daily_since` selects an additional view after full-history reconciliation.
    Supplied receipts describe a claimed invocation; this module cannot attest it.
    """
    capture, last_day = _receipt(receipt)
    if daily_since is not None and day(daily_since, "dailySince") > last_day:
        reject("future_cutoff", "dailySince")
    raw = _decode(report_bytes)
    budget = [0]
    monthly = _section(raw["monthly"], "monthly", last_day, budget)
    daily = _section(raw["daily"], "daily", last_day, budget)
    grouped = {}
    for period, row in daily.items():
        grouped.setdefault(period[:7], []).append(row)
    if set(monthly) != set(grouped):
        reject("month_day_scope_mismatch", "report.monthly")
    for i, (period, parent) in enumerate(sorted(monthly.items())):
        children = grouped[period]
        path = f"report.monthly[{i}]"
        _check_fold(parent, children, path)
        names = {name for row in children for name in row["children"]}
        if set(parent["children"]) != names:
            reject("month_day_provider_scope_mismatch", path)
        for j, name in enumerate(sorted(names)):
            _check_fold(parent["children"][name], [row["children"][name] for row in children if name in row["children"]],
                        f"{path}.agents[{j}]")
    exact_keys(raw["totals"], {*COUNTERS, "totalCost"}, "report.totals")
    totals = _token_vector(raw["totals"], "report.totals")
    if _sum_vectors(list(monthly.values()), "report.totals") != totals:
        reject("root_conservation", "report.totals")
    totals_cost = money(raw["totals"]["totalCost"], "report.totals.totalCost")
    names = {name for row in monthly.values() for name in row["children"]}
    if len(names) > MAX_PROVIDERS:
        reject("capacity", "report.providers")
    ownership = _ownership(names, capture["sourceID"], side_sources)
    providers = []
    for name in sorted(names):
        months = {period: row["children"][name] for period, row in monthly.items() if name in row["children"]}
        days = {period: row["children"][name] for period, row in daily.items() if name in row["children"]}
        rows = list(months.values())
        with localcontext() as context:
            context.prec = 256
            cost_sum = sum((row["reportedCostUsd"] for row in rows), Decimal(0))
        providers.append({"provider": name, "totals": {**{key: str(value) for key, value in _sum_vectors(rows, "providers.totals").items()},
                          "summedReportedCostUsd": money_text(cost_sum),
                          "unclassifiedComponentTokens": str(sum(row["totalTokens"] - sum(row[key] for key in COMPONENTS) for row in rows)),
                          "unallocatedModelTokens": str(sum(row["totalTokens"] - sum(model[key] for model in row["models"] for key in COMPONENTS) for row in rows))},
                          "monthly": [_public_row(row, period) for period, row in sorted(months.items())],
                          "daily": [_public_row(row, period) for period, row in sorted(days.items())],
                          "recentDaily": [_public_row(row, period) for period, row in sorted(days.items()) if daily_since is None or period >= daily_since]})
    frozen_receipt = {**capture, "reportSHA256": hashlib.sha256(report_bytes).hexdigest(),
                      "byteLength": len(report_bytes), "coverage": "unknown", "receiptAttestation": "caller-declared"}
    output = {"protocol": "frozen-native-capture-v1", "capture": frozen_receipt,
              "captureID": hashlib.sha256(canonical(frozen_receipt)).hexdigest(),
              "costBasis": "scanner-reported-value", "costCoverage": "unknown",
              "costConservation": "not-attested", "ownership": ownership,
              "totals": {**{key: str(value) for key, value in totals.items()}, "reportedCostUsd": money_text(totals_cost),
                         "unclassifiedComponentTokens": str(totals["totalTokens"] - sum(totals[key] for key in COMPONENTS)),
                         "unallocatedModelTokens": str(sum(int(provider["totals"]["unallocatedModelTokens"]) for provider in providers))},
              "monthly": [_public_row(row, period) for period, row in sorted(monthly.items())],
              "daily": [_public_row(row, period) for period, row in sorted(daily.items())],
              "recentDaily": [_public_row(row, period) for period, row in sorted(daily.items()) if daily_since is None or period >= daily_since],
              "dailySelection": {"since": daily_since, "timezone": "UTC", "basis": "filter-after-frozen-capture-v1"},
              "providers": providers}
    encoded = canonical(output)
    if len(encoded) > MAX_OUTPUT_BYTES:
        reject("capacity", "output")
    return FrozenCapture(encoded)
