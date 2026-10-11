"""Structured API errors: {code, message, request_id}. Never leaks internals."""
import logging

import asyncpg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("r2m")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def not_found(what: str = "resource") -> ApiError:
    # Same response for "missing" and "outside your scope" so tenants can't probe IDs.
    return ApiError(404, "not_found", f"{what} not found")


def forbidden(message: str = "insufficient role for this action") -> ApiError:
    return ApiError(403, "forbidden", message)


def conflict(message: str) -> ApiError:
    return ApiError(409, "conflict", message)


def _body(request: Request, code: str, message: str, **extra) -> dict:
    return {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None), **extra}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, exc: ApiError):
        return JSONResponse(_body(request, exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        fields = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]  # no input echo
        return JSONResponse(_body(request, "validation_error", "request failed validation", fields=fields), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(_body(request, code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(asyncpg.IntegrityConstraintViolationError)
    async def _integrity(request: Request, exc: asyncpg.IntegrityConstraintViolationError):
        # DB triggers/constraints are the last line of defence; report without leaking SQL detail.
        log.warning("integrity violation %s request_id=%s", type(exc).__name__, getattr(request.state, "request_id", None))
        return JSONResponse(_body(request, "invariant_violation", "request violates a data invariant"), status_code=409)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error request_id=%s", getattr(request.state, "request_id", None))
        return JSONResponse(_body(request, "internal_error", "internal error"), status_code=500)
