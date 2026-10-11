from typing import Literal
from uuid import UUID

import asyncio

from fastapi import APIRouter, Depends, Request

from ..auth import Actor, agent_installations
from ..dependencies import actor, db
from ..services import metrics_rollup

router = APIRouter(tags=["metrics"])


@router.get("/agents/{agent_id}/metrics")
async def agent_metrics(agent_id: UUID, request: Request, installation_id: UUID | None = None,
                        range: Literal["1h", "24h", "7d", "30d"] = "24h", a: Actor = Depends(actor), conn=Depends(db)):
    ids = [i["id"] for i in await agent_installations(conn, a, agent_id, installation_id)]
    start = metrics_rollup.since(range)
    bucket = "hour" if metrics_rollup.RANGES[range] <= 168 else "day"
    summary, series = await asyncio.gather(metrics_rollup.summary(request.app.state.pool, ids, start),
                                           metrics_rollup.series(request.app.state.pool, ids, start, bucket))
    return {"agent_id": agent_id, "installation_ids": ids, "range": range, "bucket": bucket,
            "summary": summary, "series": series}
