from fastapi import APIRouter, Depends

from ..auth import SdkPrincipal
from ..dependencies import db, sdk
from ..schemas import IngestBatch
from ..services import trace_ingest

router = APIRouter(tags=["ingest"])


@router.post("/ingest/events", status_code=202)
async def ingest(body: IngestBatch, p: SdkPrincipal = Depends(sdk), conn=Depends(db)):
    return await trace_ingest.ingest(conn, body.events, p)
