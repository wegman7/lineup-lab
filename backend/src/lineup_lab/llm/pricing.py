"""USD per 1M tokens. Source: Anthropic pricing, checked 2026-11-18."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_write: float
    cache_read: float


PRICES = {
    "claude-opus-5-5": Price(input=4.00, output=20.00, cache_write=5.00, cache_read=0.20),
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_write=2.50, cache_read=0.10),
}


def cost_usd(model: str, usage) -> float:
    p = PRICES[model]

    def n(field: str) -> int:
        return getattr(usage, field, None) or 0

    return (
        n("input_tokens") * p.input
        + n("output_tokens") * p.output
        + n("cache_creation_input_tokens") * p.cache_write
        + n("cache_read_input_tokens") * p.cache_read
    ) / 1_000_000
