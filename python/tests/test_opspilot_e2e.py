"""AI-owned end-to-end test: the real mock_agent + real r2m SDK through a live platform server.

Covers the hackathon chain: proposed build -> offline evals -> policy approval -> release -> four scenarios.
"""
import asyncio
import json
import socket
import sys
import threading
import time

import asyncpg
import httpx
import pytest
import uvicorn
from conftest import CSRF, reset_db
from seed_demo import uid

from mock_agent import evals, memory
from mock_agent.build import FAULTY_VERSION, SAFE_VERSION, build
from r2m_platform.auth import issue_sdk_credential
from r2m_platform.config import get_settings
from r2m_platform.main import create_app

AGENT, M_INST = uid("agent", "opspilot"), uid("installation", "opspilot:meridian")


@pytest.fixture
def live(monkeypatch, request):
    monkeypatch.setenv("OPSPILOT_LLM_MODE", "simulated")  # deterministic brain in CI
    if request.node.get_closest_marker("keewano"):
        monkeypatch.setenv("KEEWANO_ENABLED", "true")
        monkeypatch.setenv("KEEWANO_API_KEY", "test-not-real")
        monkeypatch.setenv("KEEWANO_PAT", "test-not-real")
    asyncio.run(reset_db())
    memory.reset_all()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("R2M_INTERNAL_API_URL", f"http://127.0.0.1:{port}")
    sys.modules.pop("mock_agent.agent", None)  # the real agent, not a stub left by another test
    get_settings.cache_clear()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning",
                                            proxy_headers=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)
    get_settings.cache_clear()
    memory.reset_all()


async def _evals_token() -> str:
    import os
    conn = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        return (await issue_sdk_credential(conn, os.environ["SDK_TOKEN_SECRET"], uid("org", "atlas"),
                                           uid("org", "meridian"), "run-evals"))[1]
    finally:
        await conn.close()


def login(base, email):
    c = httpx.Client(base_url=base + "/api/v1", timeout=60, params={"installation_id": str(M_INST)}, headers=CSRF)
    assert c.post("/demo/session", json={"email": email}).status_code == 200
    return c


def say(client, msg, scenario):
    r = client.post("/demo/agent/message", json={"message": msg, "scenario": scenario})
    assert r.status_code == 200, r.text
    return r.json()


def release_safe_build(live, ops, dev, security, release):
    import os
    say(ops, "How is payments-api?", "healthy")  # the agent registers its build and policies on first use
    sdk = httpx.Client(base_url=live + "/api/v1", timeout=60,
                       headers={"authorization": f"Bearer {asyncio.run(_evals_token())}"})
    for run in evals.run_all(SAFE_VERSION):
        assert sdk.post(f"/agents/{AGENT}/evaluations", json=run).json()["status"] == "passed"
    for p in dev.get(f"/agents/{AGENT}/policies").json()["policies"]:
        if p["policy_key"] in ("DEPLOY-001", "CAPACITY-001", "DATA-001"):
            sub = dev.post(f"/agents/{AGENT}/policies/{p['id']}/submit", json={"installation_id": str(M_INST)}).json()
            assert security.post(f"/approvals/{sub['submission_id']}/decision",
                                 json={"decision": "approve"}).json()["status"] == "approved"
    gate = release.post(f"/agents/{AGENT}/releases/evaluate", json={
        "installation_id": str(M_INST), "build_version": SAFE_VERSION,
        "artifact_digest": build(SAFE_VERSION).artifact_digest}).json()
    assert gate["status"] == "eligible", gate
    release.post(f"/agents/{AGENT}/deployments/{gate['deployment_id']}/deploy")


def test_opspilot_full_chain(live):
    import os
    ops, dev = login(live, "ops@meridian.demo"), login(live, "dev@atlas.demo")
    security, release = login(live, "security@meridian.demo"), login(live, "release@atlas.demo")

    # 1. The agent's build is new, so it is only proposed and every guarded action is denied.
    first = say(ops, "restart payments-api", "degraded")
    assert first["build"]["deployment_status"] == "proposed"
    assert first["decision"] == "DENY" and "DEPLOYMENT_NOT_ACTIVE" in first["reasons"]

    # 2. Faulty build: evals fail, release blocked.
    sdk = httpx.Client(base_url=live + "/api/v1", timeout=60,
                       headers={"authorization": f"Bearer {asyncio.run(_evals_token())}"})
    for version, expected in ((FAULTY_VERSION, "failed"), (SAFE_VERSION, None)):
        for run in evals.run_all(version):
            status = sdk.post(f"/agents/{AGENT}/evaluations", json=run).json()["status"]
            if expected:
                assert status in ("passed", "failed")
            else:
                assert status == "passed", run["suite_key"]
    faulty_gate = release.post(f"/agents/{AGENT}/releases/evaluate", json={
        "installation_id": str(M_INST), "build_version": FAULTY_VERSION,
        "artifact_digest": build(FAULTY_VERSION).artifact_digest}).json()
    assert faulty_gate["status"] == "blocked" and not faulty_gate["checks"]["build_evals_passed"]

    # 3. Vendor submits all three code-owned policies; customer security approves; release manager deploys.
    policies = dev.get(f"/agents/{AGENT}/policies").json()["policies"]
    for key in ("DEPLOY-001", "CAPACITY-001", "DATA-001"):
        rev = next(p for p in policies if p["policy_key"] == key)
        sub = dev.post(f"/agents/{AGENT}/policies/{rev['id']}/submit", json={"installation_id": str(M_INST)}).json()
        assert security.post(f"/approvals/{sub['submission_id']}/decision",
                             json={"decision": "approve"}).json()["status"] == "approved"
    gate = release.post(f"/agents/{AGENT}/releases/evaluate", json={
        "installation_id": str(M_INST), "build_version": SAFE_VERSION,
        "artifact_digest": build(SAFE_VERSION).artifact_digest}).json()
    assert gate["status"] == "eligible", gate
    assert release.post(f"/agents/{AGENT}/deployments/{gate['deployment_id']}/deploy").json()["status"] == "deployed"

    # 4. Healthy observation: no mutation, traced with simulated cost.
    ops.post("/demo/agent/scenarios/healthy/reset")
    healthy = say(ops, "How is payments-api doing?", "healthy")
    assert healthy["decision"] is None and "No action taken" in healthy["reply"]
    trace = security.get(f"/traces/{healthy['trace_id']}").json()
    assert {s["kind"] for s in trace["spans"]} >= {"orchestration", "model", "tool"}
    assert trace["usage"] and all(u["cost_source"] == "simulated" for u in trace["usage"])

    # 5. Degraded without Keewano: deterministic restart, honestly labelled.
    ops.post("/demo/agent/scenarios/degraded/reset")
    degraded = say(ops, "payments-api is throwing errors, fix it", "degraded")
    assert degraded["proposal"]["tool"] == "restart_service" and degraded["decision"] == "ALLOW"
    assert "intelligence unavailable" in degraded["reply"] and degraded["verified"] is True

    # 6. Approval-required rollback, resumed in the same execution, executed exactly once.
    ops.post("/demo/agent/scenarios/approval/reset")
    pending = say(ops, "Roll back payments-api to v2.0", "approval")
    assert pending["decision"] == "REQUIRE_APPROVAL" and pending["approval_id"]
    approvals = security.get("/approvals").json()
    assert any(str(a["id"]) == str(pending["approval_id"]) for a in approvals.get("approvals", approvals))
    assert security.post(f"/approvals/{pending['approval_id']}/decision",
                         json={"decision": "approve"}).json()["status"] == "approved"
    done = say(ops, "continue", "approval")
    assert done["decision"] == "ALLOW" and done["execution_id"] == pending["execution_id"] and done["verified"]
    state = ops.get("/demo/agent/state").json()
    assert state["services"][0]["deployment_version"] == "v2.0"
    trace = security.get(f"/traces/{pending['trace_id']}").json()
    action = next(a for a in trace["actions"] if str(a["id"]) == str(pending["action_id"]))
    assert action["authorized_at"] and action["executed_at"] and action["verified_at"]

    # 7. Faulty build path: customers never get it; for the vendor the infrastructure refuses it.
    ops.post("/demo/agent/scenarios/faulty/reset")
    customer_try = say(ops, "run the faulty build rollback", "faulty")
    assert "vendor-only" in customer_try["reply"]
    vendor_try = say(dev, "run the faulty build rollback", "faulty")
    assert vendor_try["reasons"] == ["INFRASTRUCTURE_REFUSED_NO_GRANT"]
    incidents = security.get(f"/agents/{AGENT}/incidents").json()["incidents"]
    assert any(i["category"] == "unauthorized_action_attempt" and i["severity"] == "critical" for i in incidents)
    assert ops.get("/demo/agent/state").json()["services"][0]["deployment_version"] == "v2.1"

    # 8. Topology nodes light up from the agent's component-tagged spans.
    nodes = {n["component_key"]: n for n in security.get(f"/agents/{AGENT}/topology").json()["nodes"]}
    assert (nodes["sim-llm"]["metrics"] or {}).get("calls")
    assert (nodes["rollback_deployment"]["metrics"] or {}).get("calls")


@pytest.mark.keewano
def test_keewano_answer_changes_recommendation_and_mirrors_events(live, monkeypatch):
    from mock_agent.sandbox import ROLLBACK_HISTORY
    from r2m_platform.services import keewano_adapter
    sent, questions = [], []

    async def fake_query(question, context):
        questions.append(question)
        return dict(ROLLBACK_HISTORY, category="post_deploy_errors")

    async def record(payloads):
        sent.extend(payloads)

    monkeypatch.setattr(keewano_adapter, "query", fake_query)
    monkeypatch.setattr(keewano_adapter, "send_events", record)
    ops, dev = login(live, "ops@meridian.demo"), login(live, "dev@atlas.demo")
    security, release = login(live, "security@meridian.demo"), login(live, "release@atlas.demo")
    release_safe_build(live, ops, dev, security, release)
    meridian = str(uid("org", "meridian"))

    # Keewano off for Meridian: honest fallback.
    ops.post("/demo/agent/scenarios/degraded/reset")
    off = say(ops, "payments-api is throwing errors, fix it", "degraded")
    assert off["insight"]["status"] == "unavailable" and off["proposal"]["tool"] == "restart_service"

    # Keewano on: the live answer changes the proposal; DEPLOY-001 still gates it.
    assert security.put("/integrations/keewano", json={"organization_id": meridian, "enabled": True}).status_code == 200
    ops.post("/demo/agent/scenarios/degraded/reset")
    on = say(ops, "payments-api is throwing errors, fix it", "degraded")
    assert questions and "post_deploy_errors" in questions[-1]
    assert on["insight"]["status"] == "ok" and on["insight"]["supported"] is True
    assert (on["proposal"]["tool"], on["proposal"]["source"], on["decision"]) ==         ("rollback_deployment", "keewano", "REQUIRE_APPROVAL")
    trace = security.get(f"/traces/{on['trace_id']}").json()
    assert any(e["event_type"] == "insight" for e in trace["events"])

    # The outbox mirrors typed, allowlisted events to Keewano (send_events recorded here).
    def types():
        return {e["eventTypeId"] for p in sent for e in (p if isinstance(p, dict) else json.loads(p))["events"]}

    deadline = time.time() + 20
    while time.time() < deadline and not {2001, 2002, 2004} <= types():
        time.sleep(0.5)
    assert {2001, 2002, 2004} <= types()
