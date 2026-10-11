from uuid import UUID

from fastapi import APIRouter, Depends

from ..auth import SdkPrincipal
from ..config import Settings
from ..dependencies import db, sdk, settings
from ..schemas import ActionResultIn, AuthorizeIn
from ..services import authorization

router = APIRouter(tags=["actions"])


@router.post("/actions/authorize")
async def authorize(body: AuthorizeIn, p: SdkPrincipal = Depends(sdk), conn=Depends(db), cfg: Settings = Depends(settings)):
    return await authorization.authorize(conn, body, cfg, p)


@router.post("/actions/{action_id}/result")
async def result(action_id: UUID, body: ActionResultIn, p: SdkPrincipal = Depends(sdk), conn=Depends(db)):
    return await authorization.record_result(conn, action_id, body, p)
