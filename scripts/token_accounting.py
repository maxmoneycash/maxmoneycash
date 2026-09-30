"""Shared token-accounting conservation rules."""

COMPONENTS = [
    "inputTokens",
    "outputTokens",
    "cacheCreationTokens",
    "cacheReadTokens",
]


def component_total(row):
    return sum(row.get(component, 0) or 0 for component in COMPONENTS)


def floor_total_tokens(row):
    """Conserve complete components without discarding provider-only tokens."""
    if all(component in row and row[component] is not None for component in COMPONENTS):
        row["totalTokens"] = max(row.get("totalTokens", 0) or 0, component_total(row))
    return row


_AUDIT_FIELDS = (*COMPONENTS, "totalTokens")


def _audit_row(row):
    """Observe explicit integer counters; never repair or coerce a row."""
    if not isinstance(row, dict):
        return dict.fromkeys(_AUDIT_FIELDS)
    return {
        key: value if type(value := row.get(key)) is int and value >= 0 else None
        for key in _AUDIT_FIELDS
    }


def _audit_fold(rows):
    if not isinstance(rows, list):
        return dict.fromkeys(_AUDIT_FIELDS)
    total = dict.fromkeys(_AUDIT_FIELDS, 0)
    for row in rows:
        values = _audit_row(row)
        for key in _AUDIT_FIELDS:
            if total[key] is None or values[key] is None:
                total[key] = None
            else:
                total[key] += values[key]
    return total


def _audit_difference(left, right):
    delta = {
        key: None if left[key] is None or right[key] is None else left[key] - right[key]
        for key in _AUDIT_FIELDS
    }
    if any(value is not None and value != 0 for value in delta.values()):
        status = "mismatch"
    elif any(value is None for value in delta.values()):
        status = "unknown"
    else:
        status = "match"
    return {
        "status": status,
        "delta": {key: None if value is None else str(value) for key, value in delta.items()},
    }


def _audit_component_residual(row):
    if any(value is None for value in row.values()):
        return None
    return str(row["totalTokens"] - sum(row[key] for key in COMPONENTS))


def audit_aggregate(totals, monthly, agents):
    """Describe arithmetic in one serialized aggregate without certifying it.

    This has no I/O and does not mutate, floor or reattribute its inputs.
    Differences are exact signed decimal strings, or None when an operand is
    unavailable. Even matching arithmetic proves neither source completeness
    nor ownership, freshness, disjointness or eligibility for ingestion/pricing.
    Existing componentTotalsConserved is only a per-row floor, not this check.
    """
    headline = _audit_row(totals)
    months = _audit_fold(monthly)
    provider_totals = [] if isinstance(agents, dict) else None
    provider_months = [] if isinstance(agents, dict) else None
    mismatched = 0
    unavailable = 0
    if isinstance(agents, dict):
        # Provider names and all other source identifiers stay out of the audit.
        for provider in agents.values():
            row = provider if isinstance(provider, dict) else {}
            total = _audit_row(row.get("totals"))
            month = _audit_fold(row.get("monthly"))
            provider_totals.append(total)
            provider_months.append(month)
            check = _audit_difference(total, month)
            mismatched += check["status"] == "mismatch"
            # One row can have both a known mismatch and unknown coordinates.
            unavailable += any(value is None for value in check["delta"].values())

    providers = _audit_fold(provider_totals)
    own_months = _audit_difference(providers, _audit_fold(provider_months))
    if mismatched:
        own_months["status"] = "mismatch"
    elif unavailable or not provider_totals:
        own_months["status"] = "unknown"
    own_months["mismatchedProviderRows"] = mismatched
    own_months["unavailableProviderRows"] = unavailable

    return {
        "scope": "serialized_aggregate_totals",
        "sourceCoverage": "unknown",
        "scopeOwnership": "unknown",
        "headlineMinusMonthly": _audit_difference(headline, months),
        "headlineMinusProviders": _audit_difference(headline, providers),
        "providersMinusOwnMonths": own_months,
        "totalMinusComponents": {
            "headline": _audit_component_residual(headline),
            "monthly": _audit_component_residual(months),
            "providers": _audit_component_residual(providers),
        },
    }
