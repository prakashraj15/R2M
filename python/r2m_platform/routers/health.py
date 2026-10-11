from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live():
    return {"status": "live"}


@router.get("/health/ready")
async def ready(request: Request):
    try:
        async with request.app.state.pool.acquire(timeout=3) as conn:
            await conn.fetchval("SELECT 1")
    except Exception:
        return JSONResponse({"status": "not_ready"}, status_code=503)  # no driver detail: may contain host names
    return {"status": "ready"}
