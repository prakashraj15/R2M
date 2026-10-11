from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from ..auth import Actor, agent_installations, installation_in_scope
from ..dependencies import actor, db
from ..errors import forbidden, not_found
from ..schemas import IncidentUpdateIn
from ..services.evidence_builder import audit, record_evidence

router = APIRouter(tags=["incidents"])


@router.get("/agents/{agent_id}/incidents")
async def incidents(agent_id: UUID, installation_id: UUID | None = None, limit: int = Query(100, ge=1, le=500),
                    a: Actor = Depends(actor), conn=Depends(db)):
    ids = [i["id"] for i in await agent_installations(conn, a, agent_id, installation_id)]
    rows = await conn.fetch(
        """SELECT x.*, e.trace_id FROM incidents x LEFT JOIN executions e ON e.id = x.execution_id
           WHERE x.installation_id = ANY($1::uuid[]) ORDER BY x.detected_at DESC LIMIT $2""", ids, limit)
    return {"incidents": [dict(r) for r in rows]}


@router.patch("/incidents/{incident_id}")
async def update_incident(incident_id: UUID, body: IncidentUpdateIn, request: Request,
                          a: Actor = Depends(actor), conn=Depends(db)):
    row = await conn.fetchrow("SELECT id, installation_id, execution_id, status FROM incidents WHERE id=$1", incident_id)
    if not row:
        raise not_found("incident")
    inst = await installation_in_scope(conn, a, row["installation_id"])
    org = next((o for o in (inst["customer_org_id"], inst["vendor_org_id"]) if a.can("incident.manage", o)), None)
    if not org:
        raise forbidden("requires incident.manage")
    async with conn.transaction():
        await conn.execute(
            """UPDATE incidents SET status=$2, resolved_at = CASE WHEN $2 = 'resolved' THEN now() END WHERE id=$1""",
            incident_id, body.status)
        change = {"incident_id": incident_id, "from": row["status"], "to": body.status, "note": body.note, "by": a.email}
        await record_evidence(conn, row["installation_id"], "incident_status_changed", change,
                              execution_id=row["execution_id"], incident_id=incident_id)
        await audit(conn, a.user_id, org, "incident.update", "incident", incident_id, request.state.request_id, change)
    return {"incident_id": incident_id, "status": body.status}
