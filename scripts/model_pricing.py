"""Reference list prices per model family.

Faithful port of commit-markets/web/src/lib/modelPricing.ts so the README
pipeline and commits.sh compute the same list-price equivalent. Keep the two
tables in sync — a divergence here is exactly how the receipt and the app
started disagreeing.

Two different numbers, deliberately kept apart:
  * cost      — what the provider actually reported. Subscription plans
                (Codex, Kimi, Grok, Hermes) report 0.
  * listValue — cost, plus a reference quote for the rows that reported 0.
                What the same tokens would have cost at published API rates.
"""
import re

# USD per 1,000,000 tokens: (input, output, cache read, cache write)
REFERENCE = {
    "anthropic-opus": (15.0, 75.0, 1.5, 18.75),
    "anthropic-sonnet": (3.0, 15.0, 0.3, 3.75),
    "anthropic-haiku": (0.8, 4.0, 0.08, 1.0),
    "openai-flagship": (1.25, 10.0, 0.125, 1.25),
    "openai-reasoning": (2.0, 8.0, 0.5, 2.0),
    "openai-4o": (2.5, 10.0, 1.25, 2.5),
    "moonshot-kimi": (0.6, 2.5, 0.15, 0.6),
    "zhipu-glm": (0.6, 2.2, 0.11, 0.6),
    "xai-grok-legacy": (3.0, 15.0, 0.75, 3.0),
    "xai-grok-4.20": (1.25, 2.5, 0.2, 1.25),
    "xai-grok-4.5": (2.0, 6.0, 0.3, 2.0),
    "xai-grok-build-0.1": (1.0, 2.0, 0.2, 1.0),
    "deepseek": (0.27, 1.1, 0.07, 0.27),
    "alibaba-qwen": (0.4, 1.2, 0.1, 0.4),
    "google-gemma": (0.1, 0.4, 0.025, 0.1),
    "free": (0.0, 0.0, 0.0, 0.0),
}


def family_of(raw):
    """Model name → REFERENCE key, or "unknown" when we have no quote."""
    if not isinstance(raw, str):
        return "unknown"
    n = raw.strip().lower()
    if not n:
        return "unknown"

    if "free" in n or n.startswith("nvidia/") or "nemotron" in n:
        return "free"

    if (n.startswith("claude") or "opus" in n or "sonnet" in n
            or "haiku" in n or "fable" in n):
        if "opus" in n or "fable" in n:
            return "anthropic-opus"
        if "haiku" in n:
            return "anthropic-haiku"
        return "anthropic-sonnet"

    if (n.startswith("gpt") or n.startswith("o1") or n.startswith("o3")
            or n.startswith("o4") or "codex" in n):
        if re.match(r"^o[1-9]", n):
            return "openai-reasoning"
        if "4o" in n:
            return "openai-4o"
        return "openai-flagship"

    if "kimi" in n or n.startswith("moonshot"):
        return "moonshot-kimi"
    if "glm" in n or n.startswith("z-ai") or "zhipu" in n:
        return "zhipu-glm"

    # Grok Build is a CLI/source. Its events can name xAI or Composer models,
    # or no model at all, so keep source placeholders unpriced.
    if "composer-2.5" in n:
        return "unknown"
    if "grok-4.20" in n:
        return "xai-grok-4.20"
    if "grok-4.5" in n:
        return "xai-grok-4.5"
    if "grok-build-0.1" in n:
        return "xai-grok-build-0.1"
    if n in ("grok-build", "grok-build-latest", "grok model unknown"):
        return "unknown"
    if "grok" in n:
        return "xai-grok-legacy"

    if "deepseek" in n:
        return "deepseek"
    if "qwen" in n:
        return "alibaba-qwen"
    if "gemma" in n or "gemini" in n or n.startswith("google"):
        return "google-gemma"

    return "unknown"


def reference_cost(name, row):
    """List price for one model row. 0 when the family has no published quote."""
    price = REFERENCE.get(family_of(name))
    if not price:
        return 0.0
    return (
        (row.get("inputTokens", 0) or 0) * price[0]
        + (row.get("outputTokens", 0) or 0) * price[1]
        + (row.get("cacheReadTokens", 0) or 0) * price[2]
        + (row.get("cacheCreationTokens", 0) or 0) * price[3]
    ) / 1_000_000


def list_value(name, row):
    """Reported cost when the provider quoted one, else the reference estimate.

    Mirrors estimatedListValue() in web/src/lib/usageValue.ts: priced rows are
    left alone so a real invoice is never double-counted against a list quote.
    """
    reported = row.get("cost", 0) or 0
    if reported > 0:
        return float(reported)
    return reference_cost(name, row)
