"""Deterministic effects and diagnosis for the synthetic payments-api.

Pure functions only: they compute *proposed* state changes. Changes are applied solely by
``world.apply_action`` inside a guarded tool, which requires a live R2M grant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SERVICE_KEY = "payments-api"


def derive_health(error_rate_pct: float, p95_latency_ms: float) -> str:
    if error_rate_pct > 15 or p95_latency_ms > 2000:
        return "critical"
    if error_rate_pct > 1 or p95_latency_ms > 500:
        return "degraded"
    return "healthy"


def rollback_effect(svc: dict[str, Any], target_version: str) -> dict[str, Any]:
    if target_version != svc.get("previous_version"):
        raise ValueError(f"no known release {target_version!r} to roll back to")
    return {"deployment_version": target_version, "previous_version": svc["deployment_version"],
            "error_rate_pct": 0.4, "p95_latency_ms": 180.0, "cpu_pct": 44.0, "memory_pct": 53.0,
            "health_status": "healthy"}


def restart_effect(svc: dict[str, Any]) -> dict[str, Any]:
    # The v2.1 defect is in code, so a restart only clears transient load.
    err = round(svc["error_rate_pct"] * 0.85, 2)
    p95 = round(svc["p95_latency_ms"] * 0.9, 1)
    return {"error_rate_pct": err, "p95_latency_ms": p95, "cpu_pct": round(svc["cpu_pct"] * 0.8, 1),
            "health_status": derive_health(err, p95)}


def scale_effect(svc: dict[str, Any], desired_replicas: int) -> dict[str, Any]:
    old = max(int(svc["replicas"]), 1)
    ratio = old / desired_replicas
    err = round(svc["error_rate_pct"] * (0.9 if desired_replicas > old else 1.0), 2)
    p95 = round(svc["p95_latency_ms"] * (0.75 if desired_replicas > old else 1 / max(ratio, 1e-6) ** 0.2), 1)
    return {"replicas": desired_replicas, "cpu_pct": round(min(99.0, svc["cpu_pct"] * ratio), 1),
            "error_rate_pct": err, "p95_latency_ms": p95, "health_status": derive_health(err, p95)}


@dataclass(frozen=True)
class Diagnosis:
    category: str  # healthy | post_deploy_errors | capacity_pressure | unknown
    severity: str  # info | warning | critical
    evidence: tuple[str, ...] = field(default_factory=tuple)

    @property
    def needs_action(self) -> bool:
        return self.category != "healthy"


def diagnose(svc: dict[str, Any], logs: list[str] | None = None) -> Diagnosis:
    health = svc["health_status"]
    if health == "healthy":
        return Diagnosis("healthy", "info", (f"error rate {svc['error_rate_pct']}%",
                                             f"p95 {svc['p95_latency_ms']} ms"))
    evidence = [f"error rate {svc['error_rate_pct']}% (threshold 1%)", f"p95 {svc['p95_latency_ms']} ms"]
    deploy_errors = [line for line in (logs or []) if svc["deployment_version"] in line and "ERROR" in line]
    severity = "critical" if health == "critical" else "warning"
    if svc.get("previous_version") and deploy_errors:
        evidence.append(f"{len(deploy_errors)} errors tagged {svc['deployment_version']} since its rollout "
                        f"(previous {svc['previous_version']})")
        return Diagnosis("post_deploy_errors", severity, tuple(evidence))
    if svc["cpu_pct"] > 85:
        evidence.append(f"cpu {svc['cpu_pct']}%")
        return Diagnosis("capacity_pressure", severity, tuple(evidence))
    return Diagnosis("unknown", severity, tuple(evidence))
