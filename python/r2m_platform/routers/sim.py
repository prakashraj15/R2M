"""Simulated infrastructure and Keewano insights for an external agent (the OpsPilot container), over HTTP.

SDK-token authenticated and row-level-security scoped to the token's vendor/customer pair. These replace the
old in-process bridge: the agent runs in its own container and reaches R2M only through the API.
"""
from uuid import UUID

from fastapi import APIRouter, Depends

from ..auth import SdkPrincipal
from ..config import Settings
from ..dependencies import db, sdk, settings
from ..errors import ApiError, not_found
from ..schemas import SimActionIn, SimInsightIn
from ..services import simulation
from ..services.insight_query import run_insight_query

router = APIRouter(prefix="/sim", tags=["simulation"])


async def _installation(conn, principal: SdkPrincipal, execution_id: UUID | None) -> UUID:
    """The installation an action belongs to: its execution's, else the pair's (RLS limits both to the pair)."""
    if execution_id:
        inst = await conn.fetchval(
            """SELECT d.installation_id FROM executions e JOIN deployments d ON d.id = e.deployment_id
               WHERE e.id=$1 AND e.customer_org_id=$2""", execution_id, principal.customer_org_id)
        if inst:
            return inst
    inst = await conn.fetchval(
        "SELECT id FROM agent_installations WHERE customer_org_id=$1 ORDER BY environment DESC, id LIMIT 1",
        principal.customer_org_id)
    if not inst:
        raise not_found("installation")
    return inst


@router.get("/context")
async def context(artifact_digest: str | None = None, p: SdkPrincipal = Depends(sdk), conn=Depends(db)):
    """Who the token belongs to: vendor, customer, environment, services, and (given its digest) the release status
    of the agent's build at this installation: proposed, eligible, blocked, deployed, retired, or unregistered."""
    names = {r["id"]: r["name"] for r in await conn.fetch(
        "SELECT id, name FROM organizations WHERE id = ANY($1::uuid[])", [p.vendor_org_id, p.customer_org_id])}
    inst = await _installation(conn, p, None)
    return {"vendor_org_id": p.vendor_org_id, "vendor_name": names.get(p.vendor_org_id),
            "customer_org_id": p.customer_org_id, "customer_name": names.get(p.customer_org_id),
            "installation_id": inst,
            "environment": await conn.fetchval("SELECT environment FROM agent_installations WHERE id=$1", inst),
            "services": [s["service_key"] for s in await simulation.services(conn, p.customer_org_id)],
            "deployment_status": await conn.fetchval(
                """SELECT d.status FROM deployments d JOIN builds b ON b.id = d.build_id
                   WHERE b.artifact_digest=$1 AND d.installation_id=$2 ORDER BY d.created_at DESC LIMIT 1""",
                artifact_digest, inst) if artifact_digest else None}


@router.get("/services/{service_key}")
async def get_service(service_key: str, p: SdkPrincipal = Depends(sdk), conn=Depends(db)):
    svc = await simulation.get_service(conn, p.customer_org_id, service_key)
    if not svc:
        raise not_found("service")
    return svc


@router.get("/services/{service_key}/history")
async def history(service_key: str, p: SdkPrincipal = Depends(sdk), conn=Depends(db)):
    return {"actions": await simulation.history(conn, p.customer_org_id, service_key)}


@router.post("/services/{service_key}/actions")
async def apply_action(service_key: str, body: SimActionIn, p: SdkPrincipal = Depends(sdk), conn=Depends(db)):
    inst = await _installation(conn, p, body.execution_id)
    try:
        return await simulation.apply_action(conn, p.customer_org_id, inst, body.tool, body.changes,
                                             body.execution_id, service_key)
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc))


@router.post("/scenarios/{scenario_id}/reset")
async def reset(scenario_id: str, p: SdkPrincipal = Depends(sdk), conn=Depends(db), cfg: Settings = Depends(settings)):
    if not cfg.is_demo:
        raise ApiError(403, "forbidden", "scenario reset is only available when APP_ENV=demo")
    if scenario_id not in simulation.BASELINES:
        raise not_found("scenario")
    return await simulation.reset(conn, p.customer_org_id, scenario_id, await _installation(conn, p, None))


@router.post("/insights")
async def insights(body: SimInsightIn, p: SdkPrincipal = Depends(sdk), conn=Depends(db), cfg: Settings = Depends(settings)):
    inst_id = body.installation_id or await _installation(conn, p, None)
    inst = await conn.fetchrow(
        "SELECT id, customer_org_id FROM agent_installations WHERE id=$1 AND customer_org_id=$2",
        inst_id, p.customer_org_id)
    if not inst:
        raise not_found("installation")
    out = await run_insight_query(conn, dict(inst), body.question, cfg.keewano_enabled)
    return {**out, "insight_id": str(out["insight_id"]) if out.get("insight_id") else None}
