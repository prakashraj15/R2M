from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends

from ..auth import Actor, agent_installations
from ..dependencies import actor, db
from ..services import metrics_rollup

router = APIRouter(tags=["metrics"])


@router.get("/agents/{agent_id}/metrics")
async def agent_metrics(agent_id: UUID, installation_id: UUID | None = None,
                        range: Literal["1h", "24h", "7d", "30d"] = "24h", a: Actor = Depends(actor), conn=Depends(db)):
    ids = [i["id"] for i in await agent_installations(conn, a, agent_id, installation_id)]
    start = metrics_rollup.since(range)
    bucket = "hour" if metrics_rollup.RANGES[range] <= 168 else "day"
    return {"agent_id": agent_id, "installation_ids": ids, "range": range, "bucket": bucket,
            "summary": await metrics_rollup.summary(conn, ids, start),
            "series": await metrics_rollup.series(conn, ids, start, bucket)}
