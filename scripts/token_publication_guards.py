"""Fail-closed checks for ordinary collection; no correction authorization.

These checks establish consistency of the supplied aggregate snapshot. They do
not prove event completeness, provider semantics, or cross-source identity.
No input is normalized, rescaled, or mutated to make a check pass.
"""
import argparse
import json
import pathlib
import re
import sys

from token_accounting import COMPONENTS

NATIVE_AGENTS = ("claude", "codex", "droid", "kimi", "opencode")
COUNTERS = (*COMPONENTS, "totalTokens")
MAX_COUNTER = 9_007_199_254_740_991


class PublicationBlocked(RuntimeError):
    def __init__(self, code, path):
        self.code, self.path = code, path
        super().__init__(
            f"{code} at {path}: inconsistent snapshot/coverage; retry collection "
            "from matching source snapshots. Keep the last-good ledger and its "
            "original generated_at. Any real reduction requires a separate "
            "reviewed correction; ordinary collection cannot authorize it."
        )


def block(code, path):
    raise PublicationBlocked(code, path)


def count(value, path):
    if type(value) is not int or not 0 <= value <= MAX_COUNTER:
        block("invalid_counter", path)
    return value


def counters(row, path):
    if not isinstance(row, dict):
        block("missing_counter_row", path)
    return {key: count(row.get(key), f"{path}.{key}") for key in COUNTERS}


def month_rows(value, key, path):
    if not isinstance(value, list):
        block("missing_monthly_coverage", path)
    result = {}
    for i, row in enumerate(value):
        row_path = f"{path}[{i}]"
        if not isinstance(row, dict):
            block("invalid_month", row_path)
        period = row.get(key)
        if not isinstance(period, str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", period) or period[:4] == "0000":
            block("invalid_month", row_path)
        if period in result:
            block("duplicate_month", row_path)
        counters(row, row_path)
        result[period] = row
    return result


def source_rows(source, key, path, require_totals=True):
    if not isinstance(source, dict):
        block("missing_source", path)
    rows = month_rows(source.get("monthly"), key, f"{path}.monthly")
    totals = source.get("totals")
    if not rows and totals == {}:
        # Explicit empty successful scanner document. It cannot stand in for a
        # provider named in a positive backbone month (checked below).
        return rows
    if not require_totals and totals is None:
        return rows
    declared = counters(totals, f"{path}.totals")
    for counter in COUNTERS:
        if sum(row[counter] for row in rows.values()) != declared[counter]:
            block("source_totals_mismatch", f"{path}.totals.{counter}")
    return rows


def validate_correction_coverage(unified, agents, corrected):
    """Require one complete, arithmetically compatible native-source partition.

    A missing month is unknown. A correction can use an explicit zero reported
    row only when that row is part of the same declared backbone partition.
    The frozen cloud baseline and side providers are outside this check.
    """
    backbone = source_rows(unified, "period", "backbone", require_totals=False)
    if not backbone:
        block("empty_backbone", "backbone.monthly")
    reported = {
        name: source_rows(agents.get(name), "month", f"reported.{name}")
        for name in NATIVE_AGENTS
    }
    truth = {
        name: source_rows(corrected.get(name), "month", f"corrected.{name}")
        for name in ("codex", "kimi")
    }
    for name in ("codex", "kimi"):
        if set(reported[name]) != set(truth[name]):
            block("correction_month_coverage_mismatch", f"corrected.{name}.monthly")
    for name, rows in reported.items():
        if not set(rows).issubset(backbone):
            block("provider_month_outside_backbone", f"reported.{name}.monthly")
    for period, row in backbone.items():
        path = f"backbone.monthly[{period}]"
        metadata = row.get("metadata")
        scope = metadata.get("agents") if isinstance(metadata, dict) else None
        if not isinstance(scope, list) or any(not isinstance(name, str) or name not in NATIVE_AGENTS for name in scope) or len(set(scope)) != len(scope):
            block("unproven_backbone_scope", f"{path}.metadata.agents")
        declared = set(scope)
        present = {name for name, rows in reported.items() if period in rows}
        if present != declared:
            block("provider_month_coverage_mismatch", f"{path}.metadata.agents")
        if not declared and any(row[key] for key in COUNTERS):
            block("unproven_backbone_scope", f"{path}.metadata.agents")
        for key in COUNTERS:
            if sum(reported[name][period][key] for name in present) != row[key]:
                block("backbone_partition_mismatch", f"{path}.{key}")
    return reported, truth


def _artifact(value, path):
    if not isinstance(value, dict):
        block("invalid_snapshot", path)
    rows = source_rows(value, "period", path)
    if not rows:
        block("empty_snapshot", f"{path}.monthly")
    return rows


def _retain_counts(previous, candidate, path):
    for key in COUNTERS:
        if key in previous:
            old = count(previous[key], f"{path}.{key}")
            new = count(candidate.get(key), f"{path}.{key}")
            if new < old:
                block("ordinary_decrease", f"{path}.{key}")


def _retain_months(previous, candidate, key, path):
    old_rows = month_rows(previous, key, f"previous.{path}")
    new_rows = month_rows(candidate, key, f"candidate.{path}")
    for period, old in old_rows.items():
        if period not in new_rows:
            block("missing_previous_month", f"{path}[{period}]")
        _retain_counts(old, new_rows[period], f"{path}[{period}]")


def _sources(value, path):
    if not isinstance(value, list):
        block("missing_source_coverage", path)
    result = {}
    for i, source in enumerate(value):
        if not isinstance(source, dict) or not isinstance(source.get("label"), str) or not source["label"]:
            block("missing_source_coverage", f"{path}[{i}]")
        if source["label"] in result:
            block("duplicate_source", f"{path}[{i}]")
        totals = source.get("totals")
        if not isinstance(totals, dict):
            block("missing_source_coverage", f"{path}[{i}].totals")
        count(totals.get("totalTokens"), f"{path}[{i}].totals.totalTokens")
        result[source["label"]] = totals
    return result


def validate_publication(previous, candidate):
    """Ordinary publication cannot erase source/period usage, even if net grows.

    Correction booleans, a revision label, or a small percentage are never an
    authorization. This function deliberately has no force/allow-drop option.
    """
    _artifact(candidate, "candidate")
    candidate_sources = _sources(candidate.get("sources"), "candidate.sources")
    candidate_agents = candidate.get("agents")
    if not isinstance(candidate_agents, dict):
        block("missing_provider_coverage", "candidate.agents")
    if previous is None:
        return
    _artifact(previous, "previous")
    _retain_counts(previous["totals"], candidate["totals"], "totals")
    _retain_months(previous["monthly"], candidate["monthly"], "period", "monthly")
    previous_agents = previous.get("agents")
    if not isinstance(previous_agents, dict):
        block("missing_provider_coverage", "previous.agents")
    for i, (name, old) in enumerate(previous_agents.items()):
        path = f"agents[{i}]"
        new = candidate_agents.get(name)
        if not isinstance(old, dict) or not isinstance(new, dict) or not isinstance(old.get("totals"), dict) or not isinstance(new.get("totals"), dict):
            block("missing_provider_coverage", path)
        _retain_counts(old["totals"], new["totals"], f"{path}.totals")
        _retain_months(old.get("monthly"), new.get("monthly"), "month", f"{path}.monthly")
    previous_sources = _sources(previous.get("sources"), "previous.sources")
    for i, (label, old) in enumerate(previous_sources.items()):
        if label not in candidate_sources:
            block("missing_previous_source", f"sources[{i}]")
        _retain_counts(old, candidate_sources[label], f"sources[{i}].totals")


def validate_input_directory(directory):
    def load(name):
        with open(directory / name) as source:
            return json.load(source)
    validate_correction_coverage(
        load("monthly.json"),
        {name: load(f"agent-{name}.json") for name in NATIVE_AGENTS},
        {name: load(f"{name}-true.json") for name in ("codex", "kimi")},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inputs = commands.add_parser("inputs")
    inputs.add_argument("directory", type=pathlib.Path)
    publication = commands.add_parser("publication")
    publication.add_argument("candidate", type=pathlib.Path)
    publication.add_argument("previous", type=pathlib.Path)
    args = parser.parse_args()
    try:
        if args.command == "inputs":
            validate_input_directory(args.directory)
        else:
            with args.candidate.open() as source:
                candidate = json.load(source)
            previous = None
            if args.previous.exists():
                with args.previous.open() as source:
                    previous = json.load(source)
            validate_publication(previous, candidate)
    except PublicationBlocked as error:
        print(f"Publication blocked: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        print("Publication blocked: unreadable/incomplete snapshot; retry collection. Keep the last-good ledger and original generated_at.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
