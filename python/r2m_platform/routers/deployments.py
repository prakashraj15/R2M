from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ..auth import Actor, agent_installations
from ..dependencies import actor, db
from ..schemas import ReleaseEvaluateIn
from ..services import registry, release_gate

router = APIRouter(tags=["deployments"])


@router.get("/agents/{agent_id}/deployments")
async def deployments(agent_id: UUID, installation_id: UUID | None = None, a: Actor = Depends(actor), conn=Depends(db)):
    ids = [i["id"] for i in await agent_installations(conn, a, agent_id, installation_id)]
    return {"deployments": await registry.deployments(conn, ids)}


@router.post("/agents/{agent_id}/releases/evaluate")
async def evaluate_release(agent_id: UUID, body: ReleaseEvaluateIn, request: Request, a: Actor = Depends(actor), conn=Depends(db)):
    inst = (await agent_installations(conn, a, agent_id, body.installation_id))[0]
    return await release_gate.evaluate(conn, a, inst, body.build_version, body.artifact_digest, request.state.request_id)


@router.post("/agents/{agent_id}/deployments/{deployment_id}/deploy")
async def deploy(agent_id: UUID, deployment_id: UUID, request: Request, a: Actor = Depends(actor), conn=Depends(db)):
    inst_id = await conn.fetchval("SELECT installation_id FROM deployments WHERE id=$1", deployment_id)
    inst = (await agent_installations(conn, a, agent_id, inst_id))[0]
    return await release_gate.deploy(conn, a, inst, deployment_id, request.state.request_id)
