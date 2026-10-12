"""Password sign-in. The session is an HMAC-signed, HttpOnly cookie; writes also need the X-R2M-CSRF header."""
import asyncio

from fastapi import APIRouter, Depends, Request, Response

from ..auth import SESSION_COOKIE, PERMISSIONS, Actor, password_version, sign_session, verify_password
from ..config import Settings
from ..dependencies import actor, db, settings
from ..errors import ApiError
from ..schemas import SessionIn
from ..services.evidence_builder import audit

router = APIRouter(tags=["session"])
FAILURES_PER_MINUTE = 5  # per account, on top of the per-IP login limit


@router.post("/auth/session")
async def create_session(body: SessionIn, request: Request, response: Response, conn=Depends(db),
                         cfg: Settings = Depends(settings)):
    email = body.email.strip().lower()
    limiter, key = request.app.state.limiter, f"login-fail:{email}"
    if limiter.over(key, FAILURES_PER_MINUTE):
        raise ApiError(429, "rate_limited", "too many failed sign-ins for this account; try again in a minute")
    user = await conn.fetchrow("SELECT id, password_hash FROM users WHERE email=$1", email)
    if not await asyncio.to_thread(verify_password, body.password, user and user["password_hash"]):
        limiter.hit(key, FAILURES_PER_MINUTE)
        raise ApiError(401, "unauthenticated", "invalid email or password")
    response.set_cookie(SESSION_COOKIE, sign_session(cfg.session_signing_key, user["id"], cfg.session_ttl_seconds,
                                                password_version(user["password_hash"])),
                        max_age=cfg.session_ttl_seconds, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")
    await audit(conn, user["id"], None, "session.create", "user", user["id"], request.state.request_id)
    return {"ok": True}


@router.delete("/auth/session")
async def end_session(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(a: Actor = Depends(actor)):
    orgs = {}
    for m in a.memberships:
        o = orgs.setdefault(m["organization_id"], {"id": m["organization_id"], "name": m["name"], "kind": m["kind"],
                                                   "slug": m["slug"], "roles": [], "permissions": set()})
        o["roles"].append(m["role"])
        o["permissions"] |= PERMISSIONS.get(m["role"], set())
    return {"user": {"id": a.user_id, "email": a.email, "display_name": a.display_name},
            "organizations": [{**o, "permissions": sorted(o["permissions"])} for o in orgs.values()]}
