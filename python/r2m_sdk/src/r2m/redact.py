"""Attribute redaction applied to everything the SDK sends (spec §5, DATA-001)."""
from __future__ import annotations

import re
from typing import Any

MAX_STRING = 512
MAX_DEPTH = 6
MAX_ITEMS = 50
REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    # "token" only as a whole key or suffix (access_token, grant-token), never counters like input_tokens.
    r"(secret|(^|[_-])token$|password|passwd|api[_-]?key|^(proxy[_-])?authorization$|cookie|credential"
    r"|private[_-]?key|(^|[_-])ssn$|card[_-]?number|iban)",
    re.IGNORECASE,
)
_PATTERNS = [
    (re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"), "Bearer [REDACTED]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"\b(?:\d[ \-]?){13,19}\b"), "[CARD]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"(?i)\b(sk|pk|ak|key)[_\-][a-z0-9]{12,}\b"), "[SECRET]"),
    (re.compile(r"(?i)(password|secret|token|api[_-]?key)\s*[=:]\s*\S+"), r"\1=[REDACTED]"),
]


def redact_text(value: str) -> str:
    for pattern, repl in _PATTERNS:
        value = pattern.sub(repl, value)
    if len(value) > MAX_STRING:
        value = value[:MAX_STRING] + "…[truncated]"
    return value


def redact(value: Any, _depth: int = 0) -> Any:
    """Return a JSON-safe, redacted copy of ``value``."""
    if _depth > MAX_DEPTH:
        return "[MAX_DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= MAX_ITEMS:
                out["_truncated_keys"] = len(value) - MAX_ITEMS
                break
            key = str(k)
            out[key] = REDACTED if _SENSITIVE_KEY.search(key) else redact(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        out_list = [redact(v, _depth + 1) for v in items[:MAX_ITEMS]]
        if len(items) > MAX_ITEMS:
            out_list.append(f"[+{len(items) - MAX_ITEMS} more]")
        return out_list
    if hasattr(value, "value") and isinstance(getattr(value, "value"), (str, int)):  # enums
        return value.value
    return redact_text(str(value))
