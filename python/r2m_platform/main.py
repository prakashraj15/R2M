"""FastAPI app: private listener on 127.0.0.1:8000, reached only through the Next.js /api proxy."""
import asyncio
import contextlib
import logging
import re
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import errors, guards
from .config import get_settings
from .database import create_pool
from .routers import (actions, agents, approvals, demo_agent, demo_auth, deployments, evaluations, evidence, health,
                      incidents, ingest, integrations, metrics, organizations, policies, traces)
from .workers import event_outbox

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.pool = await create_pool(settings)
    worker = asyncio.create_task(event_outbox.run_forever(app.state.pool)) if settings.keewano_enabled else None
    try:
        yield
    finally:
        if worker:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        await app.state.pool.close()


def create_app(lifespan=lifespan) -> FastAPI:
    app = FastAPI(title="R2M Platform API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json", redoc_url=None)
    errors.install(app)
    limiter = app.state.limiter = guards.RateLimiter()

    @app.middleware("http")
    async def edge(request: Request, call_next):  # request id, rate limit, CSRF, no-store
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = incoming if REQUEST_ID.match(incoming) else str(uuid.uuid4())
        rid = request.state.request_id
        if retry_after := limiter.check(request):
            response = JSONResponse({"code": "rate_limited", "message": "too many requests", "request_id": rid},
                                    status_code=429, headers={"Retry-After": str(retry_after)})
        elif not guards.csrf_ok(request.method, request.headers):
            response = JSONResponse({"code": "csrf_required", "message": "send header X-R2M-CSRF: 1 on writes",
                                     "request_id": rid}, status_code=403)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    for module in (health, demo_auth, organizations, agents, deployments, policies, approvals, evaluations, actions,
                   ingest, traces, metrics, incidents, evidence, integrations, demo_agent):
        app.include_router(module.router, prefix="/api/v1")
    return app


app = create_app()
