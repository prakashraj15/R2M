"""Live model for OpsPilot via the OpenAI Chat Completions API (optional; spec deviation, see live.py).

Only redacted text is sent: tool results pass through ``r2m.redact`` and DATA-001 keeps raw logs out.
Every call is a ``model`` span on the ``openai-llm`` node with real token counts. Cost is labelled
``estimated`` (list prices below, not reconciled with an invoice).
"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import httpx

from r2m import CostSource

if TYPE_CHECKING:
    from r2m import R2MClient

COMPONENT = "openai-llm"
DEFAULT_MODEL = "gpt-4o-mini"
# USD per 1K tokens (input, output). Override with OPENAI_PRICE_IN_PER_1K / OPENAI_PRICE_OUT_PER_1K.
LIST_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4.1-nano": (0.0001, 0.0004),
    "gpt-4.1-mini": (0.0004, 0.0016),
    "gpt-4.1": (0.002, 0.008),
}
_NO_TEMPERATURE = ("o1", "o3", "o4", "gpt-5")


class LiveModelError(RuntimeError):
    """The live model could not answer (missing key, HTTP error, timeout, malformed reply)."""


def configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def price(model: str) -> tuple[float, float] | None:
    env_in, env_out = os.environ.get("OPENAI_PRICE_IN_PER_1K"), os.environ.get("OPENAI_PRICE_OUT_PER_1K")
    if env_in and env_out:
        return float(env_in), float(env_out)
    return LIST_PRICES.get(model) or next((v for k, v in LIST_PRICES.items() if model.startswith(k + "-")), None)


class OpenAIChat:
    def __init__(self, client: "R2MClient", *, api_key: str | None = None, model: str | None = None,
                 base_url: str | None = None, timeout: float = 30.0, transport: httpx.BaseTransport | None = None):
        self._client = client
        self.model = model or os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL
        key = api_key or os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise LiveModelError("OPENAI_API_KEY is not set")
        self._http = httpx.Client(base_url=(base_url or os.environ.get("OPENAI_BASE_URL") or
                                            "https://api.openai.com/v1").rstrip("/"),
                                  timeout=timeout, transport=transport,
                                  headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})

    def close(self) -> None:
        self._http.close()

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
                 purpose: str = "agent_step", tool_choice: str = "auto") -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "max_completion_tokens": 700}
        if tools:
            body.update(tools=tools, tool_choice=tool_choice, parallel_tool_calls=False)
        if not self.model.startswith(_NO_TEMPERATURE):
            body["temperature"] = 0.2
        with self._client.model_call(self.model, provider="openai", purpose=purpose, component=COMPONENT,
                                     cost_source=CostSource.ESTIMATED) as call:
            try:
                resp = self._http.post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                raise LiveModelError(f"OpenAI request failed: {type(exc).__name__}") from exc
            if resp.status_code >= 400:
                code = None
                try:
                    code = resp.json().get("error", {}).get("code")
                except (ValueError, AttributeError):
                    pass
                raise LiveModelError(f"OpenAI HTTP {resp.status_code} {code or ''}".strip())
            try:
                data = resp.json()
                message = data["choices"][0]["message"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise LiveModelError("OpenAI reply malformed") from exc
            usage = data.get("usage") or {}
            tin, tout = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
            rates = price(self.model)
            call.record(input_tokens=tin, output_tokens=tout,
                        cost_usd=round(tin / 1000 * rates[0] + tout / 1000 * rates[1], 8) if rates else 0.0)
        return message


def tool_arguments(call: dict[str, Any]) -> dict[str, Any]:
    raw = (call.get("function") or {}).get("arguments") or "{}"
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return args if isinstance(args, dict) else {}
