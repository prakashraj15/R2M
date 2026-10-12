"""OpsPilot agent API for the Operations Desk UI (private listener; the desk proxies /agent-api/* to it).

The agent is a separate vendor app: it holds a per-customer R2M SDK token and talks to R2M only over HTTP
(register, authorize, ingest, /sim). Approvals happen in the R2M Control Plane.

Sign-in: the desk accepts R2M accounts. The service checks the email and password against R2M once, reads the
user's roles for this vendor/customer pair, and issues its own signed HttpOnly cookie. Who is talking to the agent
comes only from that cookie, never from the request body.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from mock_agent import agent
from mock_agent.scenarios import SCENARIOS

from .remote import R2MSim

API_URL = os.environ.get("R2M_API_URL", "http://127.0.0.1:3000")
TOKEN = os.environ.get("OPSPILOT_SDK_TOKEN", "")
VENDOR = os.environ.get("R2M_VENDOR_ORG_ID", "")
CUSTOMER = os.environ.get("R2M_CUSTOMER_ORG_ID", "")
ENVIRONMENT = os.environ.get("R2M_ENVIRONMENT", "production")
CONTROL_PLANE_URL = os.environ.get("R2M_CONTROL_PLANE_URL", "http://localhost:3000")
SESSION_KEY = os.environ.get("OPSPILOT_SESSION_KEY", "")
SESSION_COOKIE, SESSION_TTL, CSRF_HEADER = "opspilot_session", 8 * 3600, "x-r2m-csrf"
# R2M role -> what the user may do on the desk. Security reviewers watch; approvals happen in the Control Plane.
DESK_ROLES = {"customer_ops": "customer_ops", "vendor_developer": "vendor_developer",
              "vendor_release_manager": "vendor_developer", "customer_security": None}
ROLE_ORDER = ["customer_ops", "customer_security", "vendor_developer", "vendor_release_manager"]

app = FastAPI(title="OpsPilot agent API", docs_url="/agent-api/docs", openapi_url="/agent-api/openapi.json")
sim = R2MSim(API_URL, TOKEN) if TOKEN else None


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    scenario: Literal["healthy", "degraded", "approval", "faulty"] = "degraded"


class SessionIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=256)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign(payload: str) -> str:
    return _b64(hmac.new(SESSION_KEY.encode(), payload.encode(), hashlib.sha256).digest())


def _issue(user: dict) -> str:
    payload = _b64(json.dumps({**user, "exp": int(time.time()) + SESSION_TTL}).encode())
    return f"{payload}.{_sign(payload)}"


def _key() -> None:
    if len(SESSION_KEY) < 32:
        raise HTTPException(503, "OpsPilot sign-in is not configured: set OPSPILOT_SESSION_KEY (32+ characters)")


def current_user(request: Request) -> dict:
    """The signed-in desk user. Unsafe methods also need the CSRF header (cross-site pages can't set it)."""
    _key()
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(403, "missing X-R2M-CSRF header")
    try:
        payload, sig = request.cookies.get(SESSION_COOKIE, "").split(".", 1)
        user = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if hmac.compare_digest(sig, _sign(payload)) and user["exp"] > time.time():
            return user
    except (ValueError, KeyError):
        pass
    raise HTTPException(401, "sign in to the OpsPilot desk")


def operator(user: dict = Depends(current_user)) -> dict:
    if not DESK_ROLES.get(user["role"]):
        raise HTTPException(403, "your role can view the desk but not instruct OpsPilot")
    return user


def _sim() -> R2MSim:
    if not (sim and VENDOR and CUSTOMER):
        raise HTTPException(503, "OpsPilot is not configured: set OPSPILOT_SDK_TOKEN, R2M_VENDOR_ORG_ID, R2M_CUSTOMER_ORG_ID")
    return sim


@app.get("/agent-api/health")
def health():
    return {"status": "live", "configured": bool(sim and VENDOR and CUSTOMER)}


@app.post("/agent-api/session")
def sign_in(body: SessionIn, request: Request, response: Response):
    _key()
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(403, "missing X-R2M-CSRF header")
    with httpx.Client(base_url=API_URL.rstrip("/") + "/api/v1", timeout=15, headers={CSRF_HEADER: "1"}) as r2m:
        r = r2m.post("/auth/session", json={"email": body.email, "password": body.password})
        if r.status_code != 200:
            raise HTTPException(429 if r.status_code == 429 else 401,
                                "too many attempts; try again in a minute" if r.status_code == 429
                                else "invalid email or password")
        me = r2m.get("/me").json()
        r2m.delete("/auth/session")
    roles = {role for o in me["organizations"] if o["id"] in (VENDOR, CUSTOMER) for role in o["roles"]}
    role = next((x for x in ROLE_ORDER if x in roles), None)
    if not role:
        raise HTTPException(403, "this account has no access to OpsPilot for this customer")
    org = next(o["name"] for o in me["organizations"] if role in o["roles"])
    user = {"email": me["user"]["email"], "name": me["user"]["display_name"], "role": role, "organization": org}
    response.set_cookie(SESSION_COOKIE, _issue(user), max_age=SESSION_TTL, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")
    return user


@app.delete("/agent-api/session")
def sign_out(response: Response, _: dict = Depends(current_user)):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/agent-api/me")
def me(user: dict = Depends(current_user)):
    return {k: user[k] for k in ("email", "name", "role", "organization")} | {"can_instruct": bool(DESK_ROLES.get(user["role"]))}


@app.get("/agent-api/state")
def state(_: dict = Depends(current_user)):
    s = _sim()
    return {"service": s.get_service(), "history": s.deployment_history(), "scenarios": list(SCENARIOS),
            "control_plane_url": CONTROL_PLANE_URL, "environment": ENVIRONMENT}


@app.post("/agent-api/scenarios/{scenario_id}/reset")
def reset(scenario_id: str, _: dict = Depends(operator)):
    return _sim().reset(scenario_id)


@app.post("/agent-api/message")
def message(body: MessageIn, user: dict = Depends(operator)):  # sync: a worker thread, so blocking HTTP is fine
    s = _sim()
    context = {"world": s, "insights": s, "sdk_token": TOKEN, "vendor_org_id": VENDOR, "customer_org_id": CUSTOMER,
               "environment": ENVIRONMENT, "api_url": API_URL,
               "actor": {"email": user["email"], "roles": [DESK_ROLES[user["role"]]]}}
    try:
        return agent.handle_message(body.message, body.scenario, context)
    except Exception as exc:  # surface the class, never internals
        raise HTTPException(502, f"OpsPilot failed: {type(exc).__name__}")
