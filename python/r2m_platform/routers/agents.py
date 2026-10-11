from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends

from ..auth import Actor, agent_installations, scoped_installations
from ..dependencies import actor, db, sdk
from ..schemas import SdkAgentIn
from ..services import metrics_rollup, registry

router = APIRouter(tags=["agents"])


@router.get("/agents")
async def list_agents(a: Actor = Depends(actor), conn=Depends(db)):
    return {"agents": await registry.list_agents(conn, await scoped_installations(conn, a))}


@router.post("/agents", dependencies=[Depends(sdk)])
async def register_agent(body: SdkAgentIn, conn=Depends(db)):
    """SDK registration (agent, installation, build, proposed deployment, topology). Bearer token only."""
    return await registry.register_from_sdk(conn, body)


@router.get("/agents/{agent_id}/topology")
async def topology(agent_id: UUID, installation_id: UUID | None = None, range: Literal["1h", "24h", "7d", "30d"] = "24h",
                   a: Actor = Depends(actor), conn=Depends(db)):
    inst = (await agent_installations(conn, a, agent_id, installation_id))[0]
    return await registry.topology(conn, inst, metrics_rollup.since(range))
