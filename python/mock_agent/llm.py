"""Simulated, deterministic model. No vendor API is called; usage is recorded as ``simulated``."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from r2m import R2MClient

MODEL = "opspilot-sim-1"
COMPONENT = "sim-llm"
_SYSTEM_PROMPT_TOKENS = 220


@dataclass(frozen=True)
class Intent:
    kind: str  # observe | remediate | rollback | scale | restart | resume | fault_injection
    params: dict[str, Any] = field(default_factory=dict)
    explicit: bool = True  # False when inferred from the scenario default


SCENARIO_DEFAULTS = {"healthy": "observe", "degraded": "remediate", "approval": "rollback",
                     "faulty": "fault_injection"}

_RESUME = re.compile(r"\b(continue|resume|proceed|approved|go ahead|retry)\b", re.I)
_FAULT = re.compile(r"\b(fault|faulty|bypass|inject(ion)?)\b", re.I)
_ROLLBACK = re.compile(r"\broll\s?-?back\b", re.I)
_SCALE = re.compile(r"\bscale\b", re.I)
_RESTART = re.compile(r"\brestart\b", re.I)
_OBSERVE = re.compile(r"\b(status|health|healthy|how is|check|observe|look)\b", re.I)
_REMEDIATE = re.compile(r"\b(fix|remediate|mitigate|recover|what should|help|investigate|incident|errors?)\b", re.I)
_VERSION = re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b")
_NUMBER = re.compile(r"\b(\d{1,3})\b")


def _tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


class SimulatedLLM:
    def __init__(self, client: "R2MClient"):
        self._client = client

    def _call(self, purpose: str, prompt: str, completion: str) -> str:
        with self._client.model_call(MODEL, purpose=purpose, component=COMPONENT) as call:
            call.record(input_tokens=_SYSTEM_PROMPT_TOKENS + _tokens(prompt), output_tokens=_tokens(completion))
        return completion

    def classify(self, message: str, scenario: str) -> Intent:
        intent = parse_intent(message, scenario)
        self._call("classify_intent", message, f"{intent.kind} {intent.params}")
        return intent

    def summarize(self, purpose: str, facts: dict[str, Any], text: str) -> str:
        return self._call(purpose, repr(facts), text)


def parse_intent(message: str, scenario: str) -> Intent:
    msg = message or ""
    if _RESUME.search(msg):
        return Intent("resume")
    if _FAULT.search(msg):
        return Intent("fault_injection")
    if _ROLLBACK.search(msg):
        v = _VERSION.search(msg)
        return Intent("rollback", {"target_version": v.group(0)} if v else {})
    if _SCALE.search(msg):
        n = _NUMBER.search(_VERSION.sub("", msg))
        return Intent("scale", {"desired_replicas": int(n.group(1))} if n else {})
    if _RESTART.search(msg):
        return Intent("restart")
    if _REMEDIATE.search(msg):
        return Intent("remediate")
    if _OBSERVE.search(msg):
        return Intent("observe")
    return Intent(SCENARIO_DEFAULTS.get(scenario, "observe"), explicit=False)
