"""OpsPilot demo routes. Backend owns the route; the AI-owned agent is called through a fixed contract:

    mock_agent.agent.handle_message(message: str, scenario: str, context: dict) -> dict

It runs in a worker thread (sync or async both work), so the SDK's loopback HTTP calls back into this server
never block the event loop. `context["world"]` is a SimulationWorld; see docs/API_CONTRACT.md and the minimal
working example in python/tests/opspilot_stub.py.
"""
import asyncio
import importlib
import inspect
import logging
from uuid import UUID

import anyio.to_thread
from fastapi import APIRouter, Depends, Request

from ..auth import Actor, issue_sdk_credential, scoped_installations
from ..config import Settings
from ..dependencies import actor, db, settings
from ..errors import ApiError, not_found
from ..schemas import DemoMessageIn
from ..services import simulation
from ..services.evidence_builder import audit
from ..services.trace_ingest import sanitize

router = APIRouter(tags=["demo-agent"])
log = logging.getLogger("r2m.demo")


async def _demo_installation(conn, a: Actor, installation_id: UUID | None) -> dict:
    rows = [i for i in await scoped_installations(conn, a)
            if a.can("demo.use", i["customer_org_id"]) or a.can("demo.use", i["vendor_org_id"])]
    agent = await conn.fetchval("SELECT id FROM agents WHERE slug='opspilot'")
    rows = [i for i in rows if i["agent_id"] == agent and (installation_id is None or i["id"] == installation_id)]
    # Customer users land on their own org; vendors on the first linked customer.
    rows.sort(key=lambda i: i["customer_org_id"] not in a.org_ids)
    if not rows:
        raise not_found("demo installation")
    return rows[0]


def _run_agent(message: str, scenario: str, context: dict):
    fn = importlib.import_module("mock_agent.agent").handle_message
    result = fn(message, scenario, context)
    return asyncio.run(result) if inspect.iscoroutine(result) else result


@router.post("/demo/agent/message")
async def message(body: DemoMessageIn, request: Request, installation_id: UUID | None = None,
                  a: Actor = Depends(actor), conn=Depends(db), cfg: Settings = Depends(settings)):
    inst = await _demo_installation(conn, a, installation_id)
    dep = await conn.fetchrow(
        """SELECT d.id, b.version FROM deployments d JOIN builds b ON b.id = d.build_id
           WHERE d.installation_id=$1 AND d.status='deployed' ORDER BY d.deployed_at DESC NULLS LAST LIMIT 1""", inst["id"])
    if not dep:
        raise ApiError(409, "no_active_deployment", "no deployed build for this installation")
    try:
        importlib.import_module("mock_agent.agent")
    except ImportError:
        raise ApiError(503, "agent_unavailable", "mock agent package is not installed")
    context = {
        "world": simulation.SimulationWorld(request.app.state.pool, inst["customer_org_id"], inst["id"]),
        "agent_id": str(inst["agent_id"]), "installation_id": str(inst["id"]), "deployment_id": str(dep["id"]),
        "build_version": dep["version"], "customer_org_id": str(inst["customer_org_id"]),
        "vendor_org_id": str(inst["vendor_org_id"]), "environment": inst["environment"],
        "api_url": cfg.internal_api_url, "request_id": request.state.request_id,
        # Per-customer SDK token (vendor+customer scoped), not a platform-wide secret.
        "sdk_token": (await issue_sdk_credential(conn, cfg.sdk_token_secret, inst["vendor_org_id"],
                                                 inst["customer_org_id"], "demo-agent", reuse=True))[1],
        "actor": {"user_id": str(a.user_id), "email": a.email, "roles": sorted({m["role"] for m in a.memberships})},
    }
    try:
        result = await anyio.to_thread.run_sync(_run_agent, body.message, body.scenario, context)
    except Exception:
        log.exception("mock agent failed request_id=%s", request.state.request_id)
        raise ApiError(502, "agent_error", "the demo agent failed; see its trace for details")
    await audit(conn, a.user_id, inst["customer_org_id"], "demo.agent.message", "installation", inst["id"],
                request.state.request_id, {"scenario": body.scenario})
    return sanitize(result if isinstance(result, dict) else {"reply": str(result)})


@router.post("/demo/agent/scenarios/{scenario_id}/reset")
async def reset(scenario_id: str, request: Request, installation_id: UUID | None = None,
                a: Actor = Depends(actor), conn=Depends(db), cfg: Settings = Depends(settings)):
    if not cfg.is_demo:
        raise ApiError(403, "forbidden", "scenario reset is only available when APP_ENV=demo")
    if scenario_id not in simulation.BASELINES:
        raise not_found("scenario")
    inst = await _demo_installation(conn, a, installation_id)
    out = await simulation.reset(conn, inst["customer_org_id"], scenario_id, inst["id"])
    await audit(conn, a.user_id, inst["customer_org_id"], "demo.scenario.reset", "installation", inst["id"],
                request.state.request_id, {"scenario": scenario_id})
    return out


@router.get("/demo/agent/state")
async def state(installation_id: UUID | None = None, a: Actor = Depends(actor), conn=Depends(db)):
    inst = await _demo_installation(conn, a, installation_id)
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
            "notice": "Synthetic data only. No real infrastructure is touched."}
