"""OpsPilot agent API for the Operations Desk UI (private listener; the desk proxies /agent-api/* to it).

The agent is a separate vendor app: it holds a per-customer R2M SDK token and talks to R2M only over HTTP
(register, authorize, ingest, /sim). Approvals happen in the R2M Control Plane.
"""
import os
from typing import Literal

from fastapi import FastAPI, HTTPException
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

app = FastAPI(title="OpsPilot agent API", docs_url="/agent-api/docs", openapi_url="/agent-api/openapi.json")
sim = R2MSim(API_URL, TOKEN) if TOKEN else None


OPERATORS = {  # desk persona -> email; a demo label, not an auth boundary (R2M grants + release gate are)
    "customer_ops": "ops@meridian.demo",
    "vendor_developer": "dev@atlas.demo",
}


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    scenario: Literal["healthy", "degraded", "approval", "faulty"] = "degraded"
    operator: Literal["customer_ops", "vendor_developer"] = "customer_ops"


def _sim() -> R2MSim:
    if not (sim and VENDOR and CUSTOMER):
        raise HTTPException(503, "OpsPilot is not configured: set OPSPILOT_SDK_TOKEN, R2M_VENDOR_ORG_ID, R2M_CUSTOMER_ORG_ID")
    return sim


@app.get("/agent-api/health")
def health():
    return {"status": "live", "configured": bool(sim and VENDOR and CUSTOMER)}


@app.get("/agent-api/state")
def state():
    s = _sim()
    return {"service": s.get_service(), "history": s.deployment_history(), "scenarios": list(SCENARIOS),
            "control_plane_url": CONTROL_PLANE_URL, "environment": ENVIRONMENT}


@app.post("/agent-api/scenarios/{scenario_id}/reset")
def reset(scenario_id: str):
    return _sim().reset(scenario_id)


@app.post("/agent-api/message")
def message(body: MessageIn):  # sync: runs in a worker thread, so the agent's blocking HTTP calls are fine
    s = _sim()
    context = {"world": s, "insights": s, "sdk_token": TOKEN, "vendor_org_id": VENDOR, "customer_org_id": CUSTOMER,
               "environment": ENVIRONMENT, "api_url": API_URL,
               "actor": {"email": OPERATORS[body.operator], "roles": [body.operator]}}
    try:
        return agent.handle_message(body.message, body.scenario, context)
    except Exception as exc:  # surface the class, never internals
        raise HTTPException(502, f"OpsPilot failed: {type(exc).__name__}")
