"""Model invocation recording: a model span plus token usage and cost provenance."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .types import CostSource, EventKind, SpanKind
from .usage import default_cost_source, estimate_cost_usd

if TYPE_CHECKING:
    from .client import R2MClient
    from .tracing import Span


class ModelCall:
    """``with client.model_call("opspilot-sim-1", provider="simulated") as call: ...; call.record(...)``"""

    def __init__(self, client: "R2MClient", model: str, provider: str, purpose: str | None,
                 cost_source: CostSource | None):
        self._client = client
        self.model = model
        self.provider = provider
        self.cost_source = cost_source or default_cost_source(model)
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd: float | None = None
        attrs: dict[str, Any] = {"model": model, "provider": provider}
        if purpose:
            attrs["purpose"] = purpose
        self._span: "Span" = client.span(f"model:{model}", SpanKind.MODEL, attrs)

    def record(self, *, input_tokens: int, output_tokens: int, cost_usd: float | None = None) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_usd = cost_usd

    def _start(self) -> "ModelCall":
        self._span._start()
        return self

    def _finish(self, exc: BaseException | None) -> None:
        cost = self.cost_usd if self.cost_usd is not None else estimate_cost_usd(
            self.model, self.input_tokens, self.output_tokens)
        self._span.set_attributes(input_tokens=self.input_tokens, output_tokens=self.output_tokens,
                                  cost_usd=cost, cost_source=self.cost_source.value)
        span_id = self._span.id
        self._span._finish(exc)
        self._client._emit(EventKind.USAGE, f"usage:{self.model}", span_id=span_id, attributes={
            "component_kind": "model",
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "amount_usd": cost,
            "currency": "USD",
            "cost_source": self.cost_source.value,
            "measurement_kind": "tokens",
            "duration_ms": self._span.duration_ms,
        })

    def __enter__(self) -> "ModelCall":
        return self._start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self._finish(exc)

    async def __aenter__(self) -> "ModelCall":
        return self._start()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._finish(exc)
