"""Injectable DB connection, settings, browser actor and SDK credential auth.

Both auth dependencies apply the caller's row-level-security scope to the request connection and publish it in
`current_scope` for any further connections the request borrows.
"""
from typing import AsyncIterator

from fastapi import Depends, Request

from .auth import SESSION_COOKIE, Actor, SdkPrincipal, load_actor, load_sdk_principal, parse_sdk_token, verify_session
from .config import Settings, get_settings
from .database import current_scope
from .errors import ApiError


async def db(request: Request) -> AsyncIterator:
    async with request.app.state.pool.acquire() as conn:
        yield conn


def settings() -> Settings:
    return get_settings()


async def actor(request: Request, conn=Depends(db), cfg: Settings = Depends(settings)) -> Actor:
    token = request.cookies.get(SESSION_COOKIE)
    session = verify_session(cfg.session_signing_key, token) if token else None
    found = await load_actor(conn, *session) if session else None
    if not found:
        raise ApiError(401, "unauthenticated", "sign in to continue")
    current_scope.set(found[1])
    return found[0]


async def sdk(request: Request, conn=Depends(db), cfg: Settings = Depends(settings)) -> SdkPrincipal:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    credential_id = parse_sdk_token(cfg.sdk_token_secret, token) if scheme.lower() == "bearer" else None
    found = await load_sdk_principal(conn, credential_id, token) if credential_id else None
    if not found:
        raise ApiError(401, "unauthenticated", "invalid or revoked SDK token")
    current_scope.set(found[1])
    return found[0]
