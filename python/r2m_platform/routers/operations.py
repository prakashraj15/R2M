"""Browser view of the simulated payments-api for the Control Plane: state and demo reset.

The OpsPilot agent is not part of this server: it runs in its own container and reaches R2M through the SDK and
the /sim endpoints (routers/sim.py).
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ..auth import Actor, scoped_installations
from ..config import Settings
from ..dependencies import actor, db, settings
from ..errors import ApiError, not_found
from ..services import simulation
from ..services.evidence_builder import audit

router = APIRouter(tags=["operations"])


async def _installation(conn, a: Actor, installation_id: UUID | None) -> dict:
    rows = [i for i in await scoped_installations(conn, a)
            if a.can("demo.use", i["customer_org_id"]) or a.can("demo.use", i["vendor_org_id"])]
    agent = await conn.fetchval("SELECT id FROM agents WHERE slug='opspilot'")
    rows = [i for i in rows if i["agent_id"] == agent and (installation_id is None or i["id"] == installation_id)]
    # Customer users land on their own org; vendors on the installation the agent most recently reported from.
    rows.sort(key=lambda i: (i["customer_org_id"] not in a.org_ids,
                             -(i["last_heartbeat_at"].timestamp() if i["last_heartbeat_at"] else 0)))
    if not rows:
        raise not_found("installation")
    return rows[0]


@router.post("/operations/scenarios/{scenario_id}/reset")
async def reset(scenario_id: str, request: Request, installation_id: UUID | None = None,
                a: Actor = Depends(actor), conn=Depends(db), cfg: Settings = Depends(settings)):
    if not cfg.is_demo:
        raise ApiError(403, "forbidden", "scenario reset is only available when APP_ENV=demo")
    if scenario_id not in simulation.BASELINES:
        raise not_found("scenario")
    inst = await _installation(conn, a, installation_id)
    out = await simulation.reset(conn, inst["customer_org_id"], scenario_id, inst["id"])
    await audit(conn, a.user_id, inst["customer_org_id"], "demo.scenario.reset", "installation", inst["id"],
                request.state.request_id, {"scenario": scenario_id})
    return out


@router.get("/operations/state")
async def state(installation_id: UUID | None = None, a: Actor = Depends(actor), conn=Depends(db)):
    inst = await _installation(conn, a, installation_id)
    actions = await conn.fetch(
        """SELECT sa.kind, sa.authorized, sa.before_state, sa.after_state, sa.created_at, sa.tool_action_id
           FROM simulation_actions sa JOIN simulation_services s ON s.id = sa.service_id
           WHERE s.customer_org_id=$1 ORDER BY sa.created_at DESC LIMIT 20""", inst["customer_org_id"])
    pending = await conn.fetch(
        """SELECT ra.id, ra.status, ra.expires_at, t.tool_key, t.arguments, e.trace_id FROM runtime_approvals ra
           JOIN tool_actions t ON t.id = ra.action_id JOIN executions e ON e.id = t.execution_id
           WHERE e.customer_org_id=$1 AND ra.status IN ('pending','approved') ORDER BY ra.requested_at DESC""",
        inst["customer_org_id"])
    last = await conn.fetchrow(
        """SELECT e.id, e.trace_id, e.status, e.started_at FROM executions e JOIN deployments d ON d.id = e.deployment_id
           WHERE d.installation_id=$1 ORDER BY e.started_at DESC LIMIT 1""", inst["id"])
    return {"installation_id": inst["id"], "agent_id": inst["agent_id"], "customer_org_id": inst["customer_org_id"],
            "services": await simulation.services(conn, inst["customer_org_id"]),
            "scenarios": list(simulation.BASELINES), "recent_actions": [dict(r) for r in actions],
            "approvals": [dict(r) for r in pending], "last_execution": dict(last) if last else None,
            "notice": "payments-api is a synthetic service; no external infrastructure is touched."}
