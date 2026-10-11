"""Cost and latency estimation. Mock model usage must be labelled ``simulated``."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .types import CostSource

# USD per 1K tokens (input, output). Synthetic prices for the deterministic mock model only.
SIMULATED_PRICING: dict[str, tuple[float, float]] = {
    "opspilot-sim-1": (0.003, 0.015),
    "opspilot-sim-mini": (0.00025, 0.00125),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int,
                      pricing: dict[str, tuple[float, float]] | None = None) -> float:
    table = pricing if pricing is not None else SIMULATED_PRICING
    if model not in table:
        return 0.0
    in_rate, out_rate = table[model]
    return round(input_tokens / 1000 * in_rate + output_tokens / 1000 * out_rate, 8)


def default_cost_source(model: str) -> CostSource:
    return CostSource.SIMULATED if model in SIMULATED_PRICING else CostSource.ESTIMATED


@dataclass
class Stopwatch:
    started: float = field(default_factory=time.perf_counter)

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 3)
