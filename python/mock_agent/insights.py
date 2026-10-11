"""Interpretation of Keewano remediation-history answers. Results are untrusted advisory data.

The answer can only *suggest* a remediation category; whatever it says, the proposed tool call
still goes through R2M policy (DEPLOY-001 etc.). Unknown categories, junk numbers and weak
evidence are ignored, and we fall back to the deterministic safe path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ALLOWED = ("restart", "rollback", "scale")
MIN_TOTAL_SAMPLES = 20
MIN_CANDIDATE_SAMPLES = 8
MIN_SUCCESS_RATE = 0.6
UNAVAILABLE_LABEL = "intelligence unavailable"


@dataclass(frozen=True)
class Candidate:
    remediation: str
    samples: int
    successes: int

    @property
    def success_rate(self) -> float:
        return self.successes / self.samples if self.samples else 0.0


@dataclass(frozen=True)
class Insight:
    status: str  # ok | failed | unavailable
    insight_id: str | None = None
    sample_count: int | None = None
    candidates: tuple[Candidate, ...] = field(default_factory=tuple)
    best: Candidate | None = None
    supported: bool = False
    label: str = UNAVAILABLE_LABEL

    def as_dict(self) -> dict[str, Any]:
        return {"provider": "keewano", "status": self.status, "insight_id": self.insight_id,
                "sample_count": self.sample_count, "supported": self.supported, "label": self.label,
                "best": self.best.remediation if self.best else None,
                "best_success_rate": round(self.best.success_rate, 3) if self.best else None,
                "candidates": [{"remediation": c.remediation, "samples": c.samples, "successes": c.successes}
                               for c in self.candidates]}


def _nonneg_int(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(n, 10_000_000))


def interpret(response: dict[str, Any] | None) -> Insight:
    response = response if isinstance(response, dict) else {}
    status = str(response.get("status") or "unavailable")
    insight_id = str(response["insight_id"]) if response.get("insight_id") else None
    if status != "ok":
        label = UNAVAILABLE_LABEL if status == "unavailable" else f"{UNAVAILABLE_LABEL} (query {status})"
        return Insight(status if status in ("failed", "unavailable") else "failed", insight_id, label=label)

    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    candidates = []
    for row in (result.get("recommendations") or [])[:20]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("remediation", "")).strip().lower()
        if name not in ALLOWED:
            continue
        samples = _nonneg_int(row.get("samples"))
        successes = min(_nonneg_int(row.get("successes")), samples)
        candidates.append(Candidate(name, samples, successes))
    total = _nonneg_int(result.get("sample_count")) or sum(c.samples for c in candidates)
    eligible = [c for c in candidates if c.samples >= MIN_CANDIDATE_SAMPLES]
    best = max(eligible, key=lambda c: (c.success_rate, c.samples), default=None)
    supported = bool(best and total >= MIN_TOTAL_SAMPLES and best.success_rate >= MIN_SUCCESS_RATE)
    if supported:
        label = (f"Keewano history: {best.remediation} preceded recovery in {best.success_rate:.0%} "
                 f"of {best.samples} similar incidents (n={total})")
    else:
        label = f"insufficient Keewano history (n={total}); using deterministic safe fallback"
    return Insight("ok", insight_id, total, tuple(candidates), best, supported, label)
