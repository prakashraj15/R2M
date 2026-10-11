"""Injectable DB connection, settings, browser actor and SDK token auth."""
import hmac
from typing import AsyncIterator

from fastapi import Depends, Request

from .auth import SESSION_COOKIE, Actor, load_actor, verify_session
from .config import Settings, get_settings
from .errors import ApiError


async def db(request: Request) -> AsyncIterator:
    async with request.app.state.pool.acquire() as conn:
        yield conn


def settings() -> Settings:
    return get_settings()


async def actor(request: Request, conn=Depends(db), cfg: Settings = Depends(settings)) -> Actor:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = verify_session(cfg.session_signing_key, token) if token else None
    found = await load_actor(conn, user_id) if user_id else None
    if not found:
        raise ApiError(401, "unauthenticated", "sign in with a demo identity")
    return found


def sdk(request: Request, cfg: Settings = Depends(settings)) -> None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), cfg.sdk_ingest_token.encode()):
        raise ApiError(401, "unauthenticated", "invalid SDK bearer token")
