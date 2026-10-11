"""Synthetic payments-api world handed to the mock agent. No real infrastructure is ever touched.

The agent never imports the platform; the demo route passes it a SimulationWorld. A mutation is applied only if
/actions/authorize issued a live, not-yet-applied grant for the same execution and tool (the SDK's guarded tool
path does this before running the tool body). Otherwise it is refused, recorded as an unauthorized simulation
action and raised as a critical incident (the scenario-4 bypass signal).

Methods are synchronous: the agent runs in a worker thread and these bridge into the server event loop.
"""
from uuid import UUID

import anyio.from_thread

from .authorization import claim_grant
from .evidence_builder import record_evidence
from .incident_detector import open_incident

SERVICE_KEY = "payments-api"
STATE_FIELDS = ("deployment_version", "previous_version", "replicas", "cpu_pct", "memory_pct",
                "error_rate_pct", "p95_latency_ms", "health_status")
DEGRADED = {"deployment_version": "v2.1", "previous_version": "v2.0", "replicas": 3, "cpu_pct": 78.0,
            "memory_pct": 66.0, "error_rate_pct": 7.8, "p95_latency_ms": 920.0, "health_status": "degraded"}
BASELINES = {
    "healthy": {**DEGRADED, "cpu_pct": 41.0, "memory_pct": 52.0, "error_rate_pct": 0.3, "p95_latency_ms": 160.0,
                "health_status": "healthy"},
    "degraded": DEGRADED, "approval": DEGRADED, "faulty": DEGRADED,
}


def _state(row) -> dict:
    return {k: row[k] for k in STATE_FIELDS}


async def reset(conn, customer_org_id: UUID, scenario: str, installation_id: UUID) -> dict:
    """Restore the synthetic service, expire open runtime approvals and close the previous run's incidents, so the
    next demo starts clean. Traces, decisions, evidence and audit history are kept."""
    base = BASELINES[scenario]
    async with conn.transaction():
        await conn.execute(
            """INSERT INTO simulation_services(customer_org_id, service_key, environment, deployment_version, previous_version,
               replicas, cpu_pct, memory_pct, error_rate_pct, p95_latency_ms, health_status)
               VALUES ($1,$2,'production',$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (customer_org_id, service_key, environment) DO UPDATE SET
               deployment_version=EXCLUDED.deployment_version, previous_version=EXCLUDED.previous_version,
               replicas=EXCLUDED.replicas, cpu_pct=EXCLUDED.cpu_pct, memory_pct=EXCLUDED.memory_pct,
               error_rate_pct=EXCLUDED.error_rate_pct, p95_latency_ms=EXCLUDED.p95_latency_ms,
               health_status=EXCLUDED.health_status, last_transition_at=now()""",
            customer_org_id, SERVICE_KEY, *(base[k] for k in STATE_FIELDS))
        # Pending operational approvals from the previous run would otherwise leak into the new one.
        await conn.execute(
            """UPDATE runtime_approvals ra SET status='expired' FROM tool_actions a, executions e
               WHERE ra.action_id=a.id AND a.execution_id=e.id AND e.customer_org_id=$1 AND ra.status IN ('pending','approved')""",
            customer_org_id)
        closed = await conn.fetch(
            """UPDATE incidents SET status='resolved', resolved_at=now()
               WHERE installation_id=$1 AND status <> 'resolved' RETURNING id""", installation_id)
        await record_evidence(conn, installation_id, "demo_reset",
                              {"scenario": scenario, "service": base, "incidents_resolved": [r["id"] for r in closed]})
    return {"scenario": scenario, "service": {"service_key": SERVICE_KEY, **base}, "incidents_resolved": len(closed)}


async def services(conn, customer_org_id: UUID) -> list[dict]:
    rows = await conn.fetch("SELECT * FROM simulation_services WHERE customer_org_id=$1 ORDER BY service_key", customer_org_id)
    return [dict(r) for r in rows]


class SimulationWorld:
    def __init__(self, pool, customer_org_id: UUID, installation_id: UUID):
        self._pool, self.customer_org_id, self.installation_id = pool, customer_org_id, installation_id

    # ---- sync API for the agent (call from the worker thread only) ----
    def get_service(self, service_key: str = SERVICE_KEY) -> dict:
        return anyio.from_thread.run(self._get_service, service_key)

    def deployment_history(self, service_key: str = SERVICE_KEY) -> list[dict]:
        return anyio.from_thread.run(self._history, service_key)

    def apply_action(self, tool: str, changes: dict, execution_id: str | None,
                     service_key: str = SERVICE_KEY) -> dict:
        """Call from inside the tool body with r2m.current_execution().execution_id."""
        return anyio.from_thread.run(self._apply, tool, changes, execution_id, service_key)

    # ---- async implementations ----
    async def _get_service(self, service_key):
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM simulation_services WHERE customer_org_id=$1 AND service_key=$2",
                                      self.customer_org_id, service_key)
        return {"service_key": service_key, **_state(row), "last_transition_at": row["last_transition_at"].isoformat()} if row else None

    async def _history(self, service_key):
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT sa.kind, sa.before_state, sa.after_state, sa.authorized, sa.created_at FROM simulation_actions sa
                   JOIN simulation_services s ON s.id = sa.service_id WHERE s.customer_org_id=$1 AND s.service_key=$2
                   ORDER BY sa.created_at DESC LIMIT 20""", self.customer_org_id, service_key)
        return [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows]

    async def _apply(self, tool, changes, execution_id, service_key):
        unknown = set(changes) - set(STATE_FIELDS)
        if unknown:
            raise ValueError(f"unsupported state fields: {sorted(unknown)}")
        async with self._pool.acquire() as conn, conn.transaction():
            svc = await conn.fetchrow(
                "SELECT * FROM simulation_services WHERE customer_org_id=$1 AND service_key=$2 FOR UPDATE",
                self.customer_org_id, service_key)
            if not svc:
                raise ValueError("unknown simulated service")
            before = _state(svc)
            grant = await claim_grant(conn, UUID(str(execution_id)), tool, self.customer_org_id) if execution_id else None
            if not grant:
                await conn.execute(
                    """INSERT INTO simulation_actions(service_id, kind, before_state, after_state, authorized)
                       VALUES ($1,$2,$3,$3,false)""", svc["id"], tool, before)
                incident = await open_incident(
                    conn, self.installation_id, "unauthorized_action_attempt", "critical",
                    f"{tool} reached the simulated infrastructure without a valid single-use grant; refused")
                return {"applied": False, "reason": "missing_or_invalid_grant", "incident_id": str(incident), "state": before}
            after = {**before, **changes}
            await conn.execute(
                """UPDATE simulation_services SET deployment_version=$2, previous_version=$3, replicas=$4, cpu_pct=$5,
                   memory_pct=$6, error_rate_pct=$7, p95_latency_ms=$8, health_status=$9, last_transition_at=now()
                   WHERE id=$1""", svc["id"], *(after[k] for k in STATE_FIELDS))
            await conn.execute(
                """INSERT INTO simulation_actions(service_id, tool_action_id, kind, before_state, after_state, authorized)
                   VALUES ($1,$2,$3,$4,$5,true)""", svc["id"], grant["action_id"], tool, before, after)
            await record_evidence(conn, self.installation_id, "simulated_infrastructure_change",
                                  {"action_id": grant["action_id"], "grant_id": grant["id"], "tool": tool,
                                   "before": before, "after": after}, execution_id=grant["execution_id"])
        return {"applied": True, "action_id": str(grant["action_id"]), "before": before, "after": after}
