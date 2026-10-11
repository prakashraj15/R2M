from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ..auth import Actor, agent_installations
from ..dependencies import actor, db

router = APIRouter(tags=["incidents"])


@router.get("/agents/{agent_id}/incidents")
async def incidents(agent_id: UUID, installation_id: UUID | None = None, limit: int = Query(100, ge=1, le=500),
                    a: Actor = Depends(actor), conn=Depends(db)):
    ids = [i["id"] for i in await agent_installations(conn, a, agent_id, installation_id)]
    rows = await conn.fetch(
        """SELECT x.*, e.trace_id FROM incidents x LEFT JOIN executions e ON e.id = x.execution_id
           WHERE x.installation_id = ANY($1::uuid[]) ORDER BY x.detected_at DESC LIMIT $2""", ids, limit)
    return {"incidents": [dict(r) for r in rows]}
