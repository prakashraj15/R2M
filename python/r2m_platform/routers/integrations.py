"""Keewano is optional and advisory. Results are untrusted data and never authorize actions."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ..auth import Actor, installation_in_scope
from ..config import Settings
from ..dependencies import actor, db, settings
from ..errors import ApiError, not_found
from ..schemas import IntegrationToggleIn, KeewanoQueryIn
from ..services.evidence_builder import audit
from ..services.insight_query import run_insight_query
from ..workers.event_outbox import adapter

router = APIRouter(tags=["integrations"])


@router.get("/integrations/keewano")
async def status(a: Actor = Depends(actor), conn=Depends(db), cfg: Settings = Depends(settings)):
    rows = await conn.fetch(
        """SELECT c.organization_id, o.name, c.enabled, c.public_configuration, c.last_success_at,
                  (SELECT count(*) FROM integration_outbox x WHERE x.integration_id=c.id AND x.state IN ('pending','failed')) AS backlog,
                  (SELECT count(*) FROM integration_outbox x WHERE x.integration_id=c.id AND x.state='dead') AS dead
           FROM integration_configs c JOIN organizations o ON o.id = c.organization_id
           WHERE c.provider='keewano' AND c.organization_id = ANY($1::uuid[])""", a.org_ids)
    last = await conn.fetchrow(
        "SELECT status, created_at, sample_count FROM insight_queries WHERE provider='keewano' ORDER BY created_at DESC LIMIT 1")
    return {"platform_enabled": cfg.keewano_enabled, "adapter_installed": adapter() is not None,
            "organizations": [dict(r) for r in rows], "last_query": dict(last) if last else None}


@router.put("/integrations/keewano")
async def toggle(body: IntegrationToggleIn, request: Request, a: Actor = Depends(actor), conn=Depends(db)):
    if body.organization_id not in a.org_ids:
        raise not_found("organization")
    a.require("integration.configure", body.organization_id)
    await conn.execute(
        """INSERT INTO integration_configs(organization_id, provider, enabled) VALUES ($1,'keewano',$2)
           ON CONFLICT (organization_id, provider) DO UPDATE SET enabled=EXCLUDED.enabled""", body.organization_id, body.enabled)
    await audit(conn, a.user_id, body.organization_id, "integration.keewano.toggle", "organization", body.organization_id,
                request.state.request_id, {"enabled": body.enabled})
    return {"organization_id": body.organization_id, "enabled": body.enabled}


@router.post("/integrations/keewano/query")
async def query(body: KeewanoQueryIn, a: Actor = Depends(actor), conn=Depends(db), cfg: Settings = Depends(settings)):
    inst = await installation_in_scope(conn, a, body.installation_id)
    if not (a.can("integration.query", inst["customer_org_id"]) or a.can("integration.query", inst["vendor_org_id"])):
        raise ApiError(403, "forbidden", "requires integration.query")
    return await run_insight_query(conn, inst, body.question, cfg.keewano_enabled)
