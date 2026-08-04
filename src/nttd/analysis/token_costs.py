"""Model-level token pricing for cost estimation.

Prices are per 1M tokens (USD). Covers common OpenAI and Anthropic models.
When a model is not found, returns 0 cost (no error).
"""

from __future__ import annotations

# (prompt_cost_per_1M, completion_cost_per_1M)
_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o3": (10.00, 40.00),
    "o3-mini": (1.10, 4.40),
    "o4-mini": (1.10, 4.40),
    # Anthropic
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost for the given token counts.

    Tries exact match first, then prefix match (longest prefix wins).
    Returns 0.0 if model is unknown.
    """
    pricing = _PRICING.get(model)
    if pricing is None:
        best_prefix = ""
        for key in _PRICING:
            if model.startswith(key) and len(key) > len(best_prefix):
                best_prefix = key
        pricing = _PRICING.get(best_prefix) if best_prefix else None

    if pricing is None:
        return 0.0

    prompt_rate, completion_rate = pricing
    return (prompt_tokens * prompt_rate + completion_tokens * completion_rate) / 1_000_000
