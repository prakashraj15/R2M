"""Platform API tests at the HTTP level, using the SDK contract's request shapes."""
import os
import uuid
from datetime import datetime, timedelta, timezone

import anyio.to_thread
import asyncpg
import httpx
import pytest
from conftest import reset_db
from r2m.approvals import ActionGrant, GrantVerifier, arguments_hash
from seed_demo import uid

from r2m_platform.config import get_settings
from r2m_platform.database import create_pool
from r2m_platform.main import create_app
from r2m_platform.services.simulation import SimulationWorld

pytestmark = pytest.mark.anyio
TOKEN = os.environ["SDK_INGEST_TOKEN"]
SDK = {"authorization": f"Bearer {TOKEN}"}
AGENT = uid("agent", "opspilot")
MERIDIAN, NORTHWIND, ATLAS = uid("org", "meridian"), uid("org", "northwind"), uid("org", "atlas")
M_INST = uid("installation", "opspilot:meridian")
M_DEP = uid("deployment", "opspilot:meridian:1.0.0-seed")
HASH = "sha256:" + "a" * 64
DEPLOY_001 = {"id": "DEPLOY-001", "version": "1.0.0", "description": "Production rollback needs exact-action approval",
              "enforcement_point": "tool.pre_execute", "scope": "production", "owner": "atlas",
              "tools": ["rollback_deployment"], "artifact_hash": HASH, "source_file": "deployment.py"}
ARGS = {"target_version": "v2.0"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def app():
    await reset_db()
    pool = await create_pool(get_settings())
    application = create_app(lifespan=None)
    application.state.pool = pool
    yield application
    await pool.close()


async def login(app, email: str) -> httpx.AsyncClient:
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    r = await c.post("/api/v1/demo/session", json={"email": email})
    assert r.status_code == 200, r.text
    return c


def sdk_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=SDK)


def event(kind, execution_id, *, at=0, customer=MERIDIAN, deployment=M_DEP, **extra):
    return {"event_id": str(uuid.uuid4()), "schema_version": "1.0",
            "occurred_at": (datetime(2026, 10, 11, tzinfo=timezone.utc) + timedelta(seconds=at)).isoformat(),
            "vendor_org_id": str(ATLAS), "customer_org_id": str(customer), "agent_id": str(AGENT),
            "deployment_id": str(deployment), "execution_id": str(execution_id) if execution_id else None,
            "trace_id": str(execution_id) if execution_id else None, "kind": kind, "name": extra.pop("name", kind), **extra}


def gate(execution_id, **overrides):
    return {"action_id": None, "agent_id": str(AGENT), "deployment_id": str(M_DEP), "installation_id": str(M_INST),
            "customer_org_id": str(MERIDIAN), "environment": "production", "execution_id": str(execution_id),
            "trace_id": str(execution_id), "span_id": None, "tool": "rollback_deployment", "risk": "high",
            "arguments_hash": arguments_hash(ARGS), "arguments": ARGS, "local_decision": "REQUIRE_APPROVAL",
            "policies": [{"policy_id": "DEPLOY-001", "version": "1.0.0", "artifact_hash": HASH,
                          "decision": "REQUIRE_APPROVAL", "reason_code": "PRODUCTION_ROLLBACK_REQUIRES_APPROVAL"}],
            **overrides}


async def make_trace(app) -> uuid.UUID:
    ex = uuid.uuid4()
    async with sdk_client(app) as s:
        r = await s.post("/api/v1/ingest/events", json={"events": [event("execution.started", ex)]})
    assert r.json()["accepted"] == 1
    return ex


async def test_requires_session_and_sdk_token(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/v1/me")).status_code == 401
        assert (await c.post("/api/v1/ingest/events", json={"events": []})).status_code == 401
        assert (await c.post("/api/v1/agents", json={})).status_code == 401
        assert (await c.post("/api/v1/demo/session", json={"email": "intruder@evil.test"})).status_code == 401
        c.cookies.set("r2m_session", "forged.signature")
        assert (await c.get("/api/v1/me")).status_code == 401


@pytest.mark.parametrize("path", ["topology", "deployments", "policies", "traces", "metrics", "incidents", "evidence"])
async def test_agent_endpoints_are_tenant_scoped(app, path):
    url = f"/api/v1/agents/{AGENT}/{path}?installation_id={M_INST}"
    meridian, northwind = await login(app, "security@meridian.demo"), await login(app, "security@northwind.demo")
    assert (await meridian.get(url)).status_code == 200
    assert (await northwind.get(url)).status_code == 404  # same answer as "doesn't exist"


async def test_cross_tenant_direct_object_references(app):
    trace_id = await make_trace(app)
    meridian, northwind = await login(app, "security@meridian.demo"), await login(app, "security@northwind.demo")
    assert {a["customer_org_id"] for a in (await northwind.get("/api/v1/agents")).json()["agents"]} == {str(NORTHWIND)}
    assert (await northwind.get(f"/api/v1/organizations/{MERIDIAN}/overview")).status_code == 404
    assert (await meridian.get(f"/api/v1/traces/{trace_id}")).status_code == 200
    assert (await northwind.get(f"/api/v1/traces/{trace_id}")).status_code == 404
    assert (await northwind.get(f"/api/v1/agents/{AGENT}/evidence/export?installation_id={M_INST}")).status_code == 404
    assert (await northwind.get(f"/api/v1/agents/{AGENT}/traces")).json()["traces"] == []
    async with sdk_client(app) as s:
        r = await s.post("/api/v1/ingest/events", json={"events": [event("state.transition", uuid.uuid4(), customer=NORTHWIND)]})
        assert r.json()["rejected"][0]["code"] == "scope_mismatch"
        cross = (await s.post("/api/v1/actions/authorize", json=gate(uuid.uuid4(), customer_org_id=str(NORTHWIND)))).json()
        assert cross["reason_codes"] == ["TENANT_SCOPE_INVALID"]
        reg = await s.post("/api/v1/agents", json={
            "slug": "opspilot", "name": "OpsPilot", "vendor_org_id": str(MERIDIAN), "customer_org_id": str(NORTHWIND),
            "environment": "production", "build": {"version": "x", "source_digest": HASH, "artifact_digest": HASH}})
        assert reg.status_code == 403


async def test_sdk_agent_registration_never_auto_deploys(app):
    body = {"slug": "opspilot", "name": "OpsPilot", "sdk_version": "0.1.0", "vendor_org_id": str(ATLAS),
            "customer_org_id": str(MERIDIAN), "environment": "production",
            "build": {"version": "new-1.0", "source_digest": HASH, "artifact_digest": "sha256:" + "c" * 64},
            "topology": {"components": [{"component_key": "llm", "kind": "model", "label": "Sim model"},
                                        {"component_key": "orchestrator", "kind": "orchestrator", "label": "OpsPilot"}],
                         "edges": [{"source": "orchestrator", "target": "llm", "edge_kind": "calls"}]}}
    async with sdk_client(app) as s:
        first = (await s.post("/api/v1/agents", json=body)).json()
        again = (await s.post("/api/v1/agents", json=body)).json()
    assert first == again  # idempotent
    assert (first["agent_id"], first["installation_id"], first["deployment_status"]) == (str(AGENT), str(M_INST), "proposed")


async def test_policy_approval_runtime_grant_and_single_use(app):
    dev, security = await login(app, "dev@atlas.demo"), await login(app, "security@meridian.demo")
    northwind = await login(app, "security@northwind.demo")
    ex = uuid.uuid4()
    async with sdk_client(app) as s:
        reg = (await s.post(f"/api/v1/agents/{AGENT}/policies/register",
                            json={"installation_id": str(M_INST), "policies": [DEPLOY_001]})).json()["policies"][0]
        assert (reg["hash_matches"], reg["status"]) == (True, "registered")
        tampered = (await s.post(f"/api/v1/agents/{AGENT}/policies/register", json={
            "installation_id": str(M_INST), "policies": [{**DEPLOY_001, "artifact_hash": "sha256:" + "b" * 64}]})).json()
        assert tampered["policies"][0]["hash_matches"] is False

        r = (await s.post("/api/v1/actions/authorize", json=gate(ex))).json()
        assert r["decision"] == "DENY" and r["reason_codes"] == ["POLICY_NOT_APPROVED:DEPLOY-001"]  # fail closed
        r = (await s.post("/api/v1/actions/authorize", json=gate(ex, policies=[], local_decision="ALLOW"))).json()
        assert r["reason_codes"] == ["GOVERNING_POLICY_NOT_CITED:DEPLOY-001"]  # dropping the binding doesn't dodge it

    sub = (await dev.post(f"/api/v1/agents/{AGENT}/policies/{reg['revision_id']}/submit",
                          json={"installation_id": str(M_INST)})).json()
    assert (await dev.post(f"/api/v1/approvals/{sub['submission_id']}/decision", json={"decision": "approve"})).status_code == 403
    assert (await northwind.post(f"/api/v1/approvals/{sub['submission_id']}/decision", json={"decision": "approve"})).status_code == 404
    assert (await security.post(f"/api/v1/approvals/{sub['submission_id']}/decision", json={"decision": "approve"})).json()["status"] == "approved"

    async with sdk_client(app) as s:
        # Overall local "ALLOW" can't hide a per-policy REQUIRE_APPROVAL: the server takes the strictest.
        pending = (await s.post("/api/v1/actions/authorize", json=gate(ex, local_decision="ALLOW"))).json()
        assert pending["decision"] == "REQUIRE_APPROVAL" and pending["grant"] is None and pending["approval_status"] == "pending"
        action_id = pending["action_id"]
        other_args = gate(ex, action_id=action_id, arguments_hash=arguments_hash({"target_version": "v1.0"}))
        assert (await s.post("/api/v1/actions/authorize", json=other_args)).json()["reason_codes"] == ["ACTION_BINDING_MISMATCH"]
        assert (await s.post("/api/v1/actions/authorize", json=gate(ex, action_id=action_id))).json()["decision"] == "REQUIRE_APPROVAL"

    assert (await security.post(f"/api/v1/approvals/{pending['approval_id']}/decision", json={"decision": "approve"})).json()["status"] == "approved"
    async with sdk_client(app) as s:
        allowed = (await s.post("/api/v1/actions/authorize", json=gate(ex, action_id=action_id))).json()
        assert (allowed["decision"], allowed["approval_status"]) == ("ALLOW", "approved")
        # The SDK's own verifier accepts the server-signed grant (byte-compatible signing).
        GrantVerifier(TOKEN).verify(ActionGrant.from_dict(allowed["grant"]), tool="rollback_deployment",
                                    args_hash=arguments_hash(ARGS), execution_id=str(ex),
                                    customer_org_id=str(MERIDIAN), deployment_id=str(M_DEP), action_id=action_id)
        again = (await s.post("/api/v1/actions/authorize", json=gate(ex, action_id=action_id))).json()
        assert again["reason_codes"] == ["APPROVAL_CONSUMED"]  # one grant per approval

    world = SimulationWorld(app.state.pool, MERIDIAN, M_INST)
    changes = {"deployment_version": "v2.0", "previous_version": "v2.1", "error_rate_pct": 0.4, "health_status": "healthy"}
    other_exec = await anyio.to_thread.run_sync(world.apply_action, "rollback_deployment", changes, str(uuid.uuid4()))
    assert other_exec["applied"] is False  # grant is bound to its execution
    done = await anyio.to_thread.run_sync(world.apply_action, "rollback_deployment", changes, str(ex))
    assert done["applied"] and done["after"]["deployment_version"] == "v2.0"
    twice = await anyio.to_thread.run_sync(world.apply_action, "rollback_deployment", changes, str(ex))
    assert twice["applied"] is False  # single use at the infrastructure boundary

    grant = allowed["grant"]
    executed = {"grant_id": grant["grant_id"], "nonce": grant["nonce"], "phase": "executed", "outcome": "succeeded"}
    async with sdk_client(app) as s:
        assert (await s.post(f"/api/v1/actions/{action_id}/result", json={**executed, "nonce": "forged"})).json()["code"] == "grant_invalid"
        assert (await s.post(f"/api/v1/actions/{action_id}/result", json=executed)).status_code == 200
        assert (await s.post(f"/api/v1/actions/{action_id}/result", json=executed)).json()["code"] == "grant_already_consumed"
        assert (await s.post(f"/api/v1/actions/{action_id}/result", json={"phase": "verified", "outcome": "verified"})).status_code == 200

    incidents = {i["category"] for i in (await security.get(f"/api/v1/agents/{AGENT}/incidents")).json()["incidents"]}
    assert incidents == {"unauthorized_action_attempt", "policy_hash_mismatch:DEPLOY-001"}
    coverage = (await security.get(f"/api/v1/agents/{AGENT}/metrics")).json()["summary"]["policy_enforcement_coverage"]
    assert (coverage["numerator"], coverage["denominator"]) == (1, 3)
    assert all(e["integrity_ok"] for e in (await security.get(f"/api/v1/agents/{AGENT}/evidence")).json()["items"])
    trace = (await security.get(f"/api/v1/traces/{ex}")).json()
    act = next(a for a in trace["actions"] if a["id"] == action_id)
    assert act["authorized_at"] and act["executed_at"] and act["verified_at"]
    assert trace["grants"][0]["applied_at"] and trace["grants"][0]["consumed_at"]


async def test_ingest_out_of_order_and_dedup(app):
    ex, parent, child = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    child_span = event("span", ex, at=2, span_id=str(child), parent_span_id=str(parent), span_kind="tool", status="ok",
                       duration_ms=40, name="tool:get_service_health",
                       attributes={"component": "get_service_health", "api_key": "leak"})
    batch1 = [child_span, event("usage", ex, at=3, span_id=str(child),
                                attributes={"input_tokens": 120, "output_tokens": 30, "amount_usd": 0.0021,
                                            "cost_source": "simulated", "component_kind": "model"})]
    batch2 = [event("span", ex, at=1, span_id=str(parent), span_kind="orchestration", name="observe", duration_ms=500),
              event("execution.started", ex, at=0, attributes={"scenario": "healthy"}),
              event("execution.ended", ex, at=9, status="completed"),
              event("heartbeat", None)]
    async with sdk_client(app) as s:
        assert (await s.post("/api/v1/ingest/events", json={"events": batch1})).json()["accepted"] == 2
        assert (await s.post("/api/v1/ingest/events", json={"events": batch2})).json()["accepted"] == 4
        assert (await s.post("/api/v1/ingest/events", json={"events": batch1})).json()["duplicates"] == 2
    ops = await login(app, "ops@meridian.demo")
    t = (await ops.get(f"/api/v1/traces/{ex}")).json()
    spans = {s["id"]: s for s in t["spans"]}
    assert spans[str(child)]["depth"] == 1 and spans[str(parent)]["kind"] == "orchestration"
    assert spans[str(child)]["attributes"]["api_key"] == "[redacted]" and spans[str(child)]["ended_at"]
    assert (t["execution"]["status"], t["execution"]["scenario"]) == ("completed", "healthy")
    assert (t["usage"][0]["cost_source"], t["usage"][0]["input_tokens"]) == ("simulated", 120)


async def test_release_gate_blocks_failing_build(app):
    release = await login(app, "release@atlas.demo")
    digest = lambda c: "sha256:" + c * 64  # noqa: E731

    def run(version, d, status):
        return {"build": {"version": version, "source_digest": digest("1"), "artifact_digest": digest(d)},
                "suite_key": "opspilot.policy_regression", "suite_description": "Policy regression", "cases": [
                    {"case_key": "rollback_requires_grant", "status": status}]}

    async with sdk_client(app) as s:
        assert (await s.post(f"/api/v1/agents/{AGENT}/evaluations", json=run("faulty-1.0", "f", "failed"))).json()["status"] == "failed"
        assert (await s.post(f"/api/v1/agents/{AGENT}/evaluations", json=run("safe-1.0", "5", "passed"))).json()["status"] == "passed"
    body = {"installation_id": str(M_INST)}
    faulty = (await release.post(f"/api/v1/agents/{AGENT}/releases/evaluate",
                                 json={**body, "build_version": "faulty-1.0", "artifact_digest": digest("f")})).json()
    assert faulty["status"] == "blocked" and not faulty["checks"]["build_evals_passed"]
    blocked = await release.post(f"/api/v1/agents/{AGENT}/deployments/{faulty['deployment_id']}/deploy")
    assert blocked.status_code == 409 and blocked.json()["code"] == "release_blocked"
    wrong = (await release.post(f"/api/v1/agents/{AGENT}/releases/evaluate",
                                json={**body, "build_version": "safe-1.0", "artifact_digest": digest("9")})).json()
    assert not wrong["checks"]["artifact_hash_matches"]
    safe = (await release.post(f"/api/v1/agents/{AGENT}/releases/evaluate",
                               json={**body, "build_version": "safe-1.0", "artifact_digest": digest("5")})).json()
    assert safe["status"] == "eligible", safe
    assert (await release.post(f"/api/v1/agents/{AGENT}/deployments/{safe['deployment_id']}/deploy")).json()["status"] == "deployed"
    ops = await login(app, "ops@meridian.demo")
    assert (await ops.post(f"/api/v1/agents/{AGENT}/releases/evaluate",
                           json={**body, "build_version": "safe-1.0", "artifact_digest": digest("5")})).status_code == 403


async def test_database_invariants(app):
    dev, security = await login(app, "dev@atlas.demo"), await login(app, "security@meridian.demo")
    async with sdk_client(app) as s:
        rev = (await s.post(f"/api/v1/agents/{AGENT}/policies/register", json={"policies": [DEPLOY_001]})).json()["policies"][0]
    sub = (await dev.post(f"/api/v1/agents/{AGENT}/policies/{rev['revision_id']}/submit", json={"installation_id": str(M_INST)})).json()
    async with app.state.pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):  # self-approval blocked below the API too
            await conn.execute("INSERT INTO approval_decisions(submission_id, decided_by, decision) VALUES ($1,$2,'approve')",
                               sub["submission_id"], uid("user", "dev@atlas.demo"))
        with pytest.raises(asyncpg.CheckViolationError):  # northwind reviewer can't decide meridian submission
            await conn.execute("INSERT INTO approval_decisions(submission_id, decided_by, decision) VALUES ($1,$2,'approve')",
                               sub["submission_id"], uid("user", "security@northwind.demo"))
        with pytest.raises(asyncpg.CheckViolationError):  # edge across installations
            await conn.execute("INSERT INTO component_edges(installation_id, source_component_id, target_component_id) VALUES ($1,$2,$3)",
                               M_INST, uid("component", "meridian:orchestrator"), uid("component", "northwind:sim-llm"))
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("UPDATE audit_events SET action='tampered'")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("DELETE FROM evidence_items")
    assert (await security.post(f"/api/v1/approvals/{sub['submission_id']}/decision", json={"decision": "reject"})).json()["status"] == "rejected"
