from uuid import UUID

from fastapi import APIRouter, Depends

from ..config import Settings
from ..dependencies import db, sdk, settings
from ..schemas import ActionResultIn, AuthorizeIn
from ..services import authorization

router = APIRouter(tags=["actions"], dependencies=[Depends(sdk)])


@router.post("/actions/authorize")
async def authorize(body: AuthorizeIn, conn=Depends(db), cfg: Settings = Depends(settings)):
    return await authorization.authorize(conn, body, cfg)


@router.post("/actions/{action_id}/result")
async def result(action_id: UUID, body: ActionResultIn, conn=Depends(db)):
    return await authorization.record_result(conn, action_id, body)
