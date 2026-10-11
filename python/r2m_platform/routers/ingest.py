from fastapi import APIRouter, Depends

from ..dependencies import db, sdk
from ..schemas import IngestBatch
from ..services import trace_ingest

router = APIRouter(tags=["ingest"], dependencies=[Depends(sdk)])


@router.post("/ingest/events", status_code=202)
async def ingest(body: IngestBatch, conn=Depends(db)):
    return await trace_ingest.ingest(conn, body.events)
