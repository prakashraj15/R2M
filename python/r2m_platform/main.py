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
from .database import create_pool, current_scope
from .routers import (actions, agents, approvals, deployments, evaluations, evidence, health, operations, session,
                      incidents, ingest, integrations, metrics, organizations, policies, sim, traces)
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


class EdgeMiddleware:
    """Request id, rate limit, CSRF and no-store, as plain ASGI.

    Not BaseHTTPMiddleware: that runs the app as a cancellable child task, and a client disconnect mid-request
    cancelled database work inside an open transaction, leaking an "idle in transaction" session that held row
    locks (demo reset/resume then hung). Plain ASGI lets every request finish its transaction.
    """

    def __init__(self, app, limiter: guards.RateLimiter):
        self.app, self.limiter = app, limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if REQUEST_ID.match(incoming) else str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = rid
        scope_token = current_scope.set(None)  # each request starts with no row-level-security scope
        try:
            return await self._handle(scope, receive, send, request, rid)
        finally:
            current_scope.reset(scope_token)

    async def _handle(self, scope, receive, send, request, rid):

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", [])
                           if k.lower() not in (b"x-request-id", b"cache-control")]
                message = {**message, "headers": headers + [(b"x-request-id", rid.encode()), (b"cache-control", b"no-store")]}
            await send(message)

        if retry_after := self.limiter.check(request):
            response = JSONResponse({"code": "rate_limited", "message": "too many requests", "request_id": rid},
                                    status_code=429, headers={"Retry-After": str(retry_after)})
        elif not guards.csrf_ok(request.method, request.headers):
            response = JSONResponse({"code": "csrf_required", "message": "send header X-R2M-CSRF: 1 on writes",
                                     "request_id": rid}, status_code=403)
        else:
            return await self.app(scope, receive, send_with_headers)
        await response(scope, receive, send_with_headers)


def create_app(lifespan=lifespan) -> FastAPI:
    app = FastAPI(title="R2M Platform API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json", redoc_url=None)
    errors.install(app)
    app.state.limiter = guards.RateLimiter()
    app.add_middleware(EdgeMiddleware, limiter=app.state.limiter)

    for module in (health, session, organizations, agents, deployments, policies, approvals, evaluations, actions,
                   ingest, traces, metrics, incidents, evidence, integrations, operations, sim):
        app.include_router(module.router, prefix="/api/v1")
    return app


app = create_app()
