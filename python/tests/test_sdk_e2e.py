"""End to end through a live server: browser roles + demo route + the real r2m SDK over loopback HTTP."""
import asyncio
import os
import socket
import sys
import threading
import time

import httpx
import pytest
import uvicorn
from conftest import reset_db
from seed_demo import uid

import opspilot_stub
from r2m_platform.config import get_settings
from r2m_platform.main import create_app

AGENT, M_INST = uid("agent", "opspilot"), uid("installation", "opspilot:meridian")


@pytest.fixture
def live(monkeypatch):
    asyncio.run(reset_db())
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("R2M_INTERNAL_API_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setitem(sys.modules, "mock_agent.agent", opspilot_stub)
    get_settings.cache_clear()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)
    get_settings.cache_clear()


def login(base, email):
    c = httpx.Client(base_url=base + "/api/v1", timeout=30)
    assert c.post("/demo/session", json={"email": email}).status_code == 200
    return c


def test_full_governance_chain_with_real_sdk(live):
    ops, dev = login(live, "ops@meridian.demo"), login(live, "dev@atlas.demo")
    security, release = login(live, "security@meridian.demo"), login(live, "release@atlas.demo")
    say = lambda msg: ops.post("/demo/agent/message", json={"message": msg, "scenario": "approval"}).json()  # noqa: E731

    # 1. New build registered by the SDK is only "proposed": it cannot act until released.
    first = say("rollback")
    assert first["deployment_status"] == "proposed"
    assert first["decision"] == "DENY" and "DEPLOYMENT_NOT_ACTIVE" in first["reasons"]

    # 2. Release: evals pass, vendor submits DEPLOY-001, customer security approves, release manager deploys.
    sdk = httpx.Client(base_url=live + "/api/v1", headers={"authorization": f"Bearer {os.environ['SDK_INGEST_TOKEN']}"})
    b = opspilot_stub.BUILD
    assert sdk.post(f"/agents/{AGENT}/evaluations", json={
        "build": {"version": b["build_version"], "source_digest": b["source_digest"], "artifact_digest": b["artifact_digest"]},
        "suite_key": "opspilot.policy_regression", "suite_description": "Policy regression",
        "cases": [{"case_key": "rollback_requires_grant", "status": "passed"}]}).json()["status"] == "passed"
    rev = next(p for p in dev.get(f"/agents/{AGENT}/policies").json()["policies"] if p["policy_key"] == "DEPLOY-001")
    assert rev["artifact_hash"] == opspilot_stub.deploy_001.artifact_hash
    sub = dev.post(f"/agents/{AGENT}/policies/{rev['id']}/submit", json={"installation_id": str(M_INST)}).json()
    assert security.post(f"/approvals/{sub['submission_id']}/decision", json={"decision": "approve"}).json()["status"] == "approved"
    gate = release.post(f"/agents/{AGENT}/releases/evaluate", json={
        "installation_id": str(M_INST), "build_version": b["build_version"], "artifact_digest": b["artifact_digest"]}).json()
    assert gate["status"] == "eligible", gate
    assert release.post(f"/agents/{AGENT}/deployments/{gate['deployment_id']}/deploy").json()["status"] == "deployed"

    # 3. Rollback needs an exact-action approval; after approval the resumed action runs exactly once.
    pending = say("rollback")
    assert pending["decision"] == "REQUIRE_APPROVAL"
    assert security.post(f"/approvals/{pending['approval_id']}/decision", json={"decision": "approve"}).json()["status"] == "approved"
    done = say(f"resume {pending['action_id']} {pending['execution_id']}")
    assert done["result"]["applied"] is True and done["result"]["after"]["deployment_version"] == "v2.0"
    replay = say(f"resume {pending['action_id']} {pending['execution_id']}")
    assert replay["decision"] == "DENY" and "APPROVAL_CONSUMED" in replay["reasons"]

    # 4. Faulty-build path: an unguarded mutation is refused at the simulated infrastructure and raises an incident.
    bypass = say("bypass")
    assert bypass["result"]["applied"] is False
    assert "unauthorized_action_attempt" in {i["category"] for i in security.get(f"/agents/{AGENT}/incidents").json()["incidents"]}

    # 5. Evidence trail: one action with authorized/executed timestamps, grant applied and consumed, spans ingested.
    trace = security.get(f"/traces/{pending['trace_id']}").json()
    action = next(a for a in trace["actions"] if a["id"] == pending["action_id"])
    assert action["authorized_at"] and action["executed_at"] and action["outcome"] == "succeeded"
    assert trace["grants"][0]["applied_at"] and trace["grants"][0]["consumed_at"]
    assert any(s["kind"] == "tool" and s["status"] != "placeholder" for s in trace["spans"])
    assert ops.get("/demo/agent/state").json()["services"][0]["deployment_version"] == "v2.0"
