"""DEMO AUTH — selects an allowlisted seeded identity. Not production authentication."""
from fastapi import APIRouter, Depends, Request, Response

from ..auth import SESSION_COOKIE, PERMISSIONS, Actor, sign_session
from ..config import Settings
from ..dependencies import actor, db, settings
from ..errors import ApiError
from ..schemas import DemoSessionIn
from ..services.evidence_builder import audit

router = APIRouter(tags=["session"])


@router.get("/auth/identities")
async def identities(conn=Depends(db)):
    rows = await conn.fetch(
        """SELECT u.email, u.display_name, o.name AS organization, o.kind AS organization_kind, m.role
           FROM users u JOIN org_memberships m ON m.user_id = u.id JOIN organizations o ON o.id = m.organization_id
           WHERE u.is_demo ORDER BY o.name, m.role""")
    return {"identities": [dict(r) for r in rows], "notice": "Demo identities only. Not production authentication."}


@router.post("/auth/session")
async def create_session(body: DemoSessionIn, request: Request, response: Response, conn=Depends(db),
                         cfg: Settings = Depends(settings)):
    user = await conn.fetchrow("SELECT id FROM users WHERE email=$1 AND is_demo", body.email.lower())
    if not user:
        raise ApiError(401, "unauthenticated", "not an allowlisted demo identity")
    response.set_cookie(SESSION_COOKIE, sign_session(cfg.session_signing_key, user["id"], cfg.session_ttl_seconds),
                        max_age=cfg.session_ttl_seconds, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")
    await audit(conn, user["id"], None, "demo.session.create", "user", user["id"], request.state.request_id)
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
            "organizations": [{**o, "permissions": sorted(o["permissions"])} for o in orgs.values()],
            "demo_auth": True}
