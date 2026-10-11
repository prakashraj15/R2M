from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from ..auth import Actor, agent_installations
from ..dependencies import actor, db
from ..errors import forbidden
from ..services import evidence_builder

router = APIRouter(tags=["evidence"])


@router.get("/agents/{agent_id}/evidence")
async def evidence(agent_id: UUID, installation_id: UUID | None = None, limit: int = Query(200, ge=1, le=1000),
                   a: Actor = Depends(actor), conn=Depends(db)):
    ids = [i["id"] for i in await agent_installations(conn, a, agent_id, installation_id)]
    return {"items": await evidence_builder.list_evidence(conn, ids, limit), "caveat": evidence_builder.CAVEAT}


@router.get("/agents/{agent_id}/evidence/export")
async def export(agent_id: UUID, request: Request, installation_id: UUID | None = None,
                 a: Actor = Depends(actor), conn=Depends(db)):
    installs = [i for i in await agent_installations(conn, a, agent_id, installation_id)
                if a.can("evidence.export", i["customer_org_id"]) or a.can("evidence.export", i["vendor_org_id"])]
    if not installs:
        raise forbidden("requires evidence.export")
    bundle = await evidence_builder.export_bundle(conn, [i["id"] for i in installs])
    await evidence_builder.audit(conn, a.user_id, a.org_ids[0], "evidence.export", "agent", agent_id,
                                 request.state.request_id, {"manifest_sha256": bundle["manifest_sha256"],
                                                            "items": len(bundle["items"])})
    return bundle
