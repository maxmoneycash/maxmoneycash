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
