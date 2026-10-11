"""Keewano outbox/query plumbing (with a fake adapter) and repeatable demo reset."""
import sys
import types
import uuid

import anyio.to_thread
import pytest
from conftest import bypass
from test_platform import AGENT, M_INST, MERIDIAN, anyio_backend, app, event, login, sdk_client  # noqa: F401

from r2m_platform.config import get_settings
from r2m_platform.services.simulation import SimulationWorld
from r2m_platform.workers import event_outbox

pytestmark = pytest.mark.anyio


@pytest.fixture
def keewano(monkeypatch):
    fake = types.ModuleType("keewano_adapter")
    fake.fail, fake.sent = False, []
    fake.map_event = lambda e: {"event_id": 2002, "value": e["name"]} if e["kind"] == "state.transition" else None

    async def send_events(payloads):
        if fake.fail:
            raise TimeoutError("keewano down")
        fake.sent.extend(payloads)

    async def query(question, context):
        if fake.fail:
            raise ConnectionError("mcp down")
        return {"sample_count": 42, "best_remediation": "rollback", "request_id": "q-1", "api_key": "leak"}

    fake.send_events, fake.query = send_events, query
    monkeypatch.setitem(sys.modules, "r2m_platform.services.keewano_adapter", fake)
    monkeypatch.setenv("KEEWANO_ENABLED", "true")
    monkeypatch.setenv("KEEWANO_API_KEY", "test-key")
    monkeypatch.setenv("KEEWANO_PAT", "test-pat")
    get_settings.cache_clear()
    yield fake
    get_settings.cache_clear()


async def _outbox(app):
    async with app.state.pool.acquire() as c:
        await bypass(c)
        return [dict(r) for r in await c.fetch("SELECT * FROM integration_outbox ORDER BY next_attempt_at")]


async def test_outbox_retries_then_sends_and_dead_letters(app, keewano):
    security = await login(app, "security@meridian.demo")
    query = {"installation_id": str(M_INST), "question": "which remediation recovered post-deploy errors?"}
    assert (await security.post("/api/v1/integrations/keewano/query", json=query)).json()["status"] == "unavailable"
    assert (await security.put("/api/v1/integrations/keewano", json={"organization_id": str(MERIDIAN), "enabled": True})).status_code == 200

    ex = uuid.uuid4()
    async with sdk_client(app) as s:
        await s.post("/api/v1/ingest/events", json={"events": [event("execution.started", ex),
                                                                event("state.transition", ex, at=1, name="OBSERVE->DIAGNOSE")]})
    [row] = await _outbox(app)  # only the mapped event is mirrored
    assert row["state"] == "pending"

    keewano.fail = True
    assert await event_outbox.drain_once(app.state.pool) == 0
    [row] = await _outbox(app)
    assert (row["state"], row["attempts"], row["last_error_class"]) == ("failed", 1, "TimeoutError")

    keewano.fail = False
    async with app.state.pool.acquire() as c:
        await bypass(c)
        await c.execute("UPDATE integration_outbox SET next_attempt_at = now()")
    assert await event_outbox.drain_once(app.state.pool) == 1
    assert (await _outbox(app))[0]["state"] == "sent" and keewano.sent == [{"event_id": 2002, "value": "OBSERVE->DIAGNOSE"}]

    async with sdk_client(app) as s:
        await s.post("/api/v1/ingest/events", json={"events": [event("state.transition", ex, at=2, name="DIAGNOSE->PROPOSE")]})
    async with app.state.pool.acquire() as c:
        await bypass(c)
        await c.execute(f"UPDATE integration_outbox SET attempts = {event_outbox.MAX_ATTEMPTS - 1} WHERE state='pending'")
    keewano.fail = True
    await event_outbox.drain_once(app.state.pool)
    assert sorted(r["state"] for r in await _outbox(app)) == ["dead", "sent"]

    status = (await security.get("/api/v1/integrations/keewano")).json()
    assert status["platform_enabled"] and status["adapter_installed"]
    assert (status["organizations"][0]["dead"], status["organizations"][0]["last_success_at"] is not None) == (1, True)

    keewano.fail = False
    ok = (await security.post("/api/v1/integrations/keewano/query", json=query)).json()
    assert ok["status"] == "ok" and ok["result"]["sample_count"] == 42 and ok["result"]["api_key"] == "[redacted]"
    keewano.fail = True
    assert (await security.post("/api/v1/integrations/keewano/query", json=query)).json()["status"] == "failed"
    northwind = await login(app, "security@northwind.demo")
    assert (await northwind.get("/api/v1/integrations/keewano")).json()["last_query"] is None  # no cross-tenant leak
    assert (await security.get("/api/v1/integrations/keewano")).json()["last_query"]["status"] == "failed"


async def test_demo_reset_restores_state_and_closes_incidents(app):
    world = SimulationWorld(app.state.pool, MERIDIAN, M_INST)
    await anyio.to_thread.run_sync(world.apply_action, "scale_instances", {"replicas": 9}, None)  # unauthorized
    ops = await login(app, "ops@meridian.demo")
    overview = f"/api/v1/organizations/{MERIDIAN}/overview"
    assert (await ops.get(overview)).json()["metrics"]["unresolved_high_severity_findings"] == 1
    reset = (await ops.post("/api/v1/demo/agent/scenarios/healthy/reset")).json()
    assert reset["incidents_resolved"] == 1 and reset["service"]["health_status"] == "healthy"
    assert (await ops.get(overview)).json()["metrics"]["unresolved_high_severity_findings"] == 0
    assert (await ops.get("/api/v1/demo/agent/state")).json()["services"][0]["error_rate_pct"] == 0.3
    evidence = (await ops.get(f"/api/v1/agents/{AGENT}/evidence")).json()["items"]
    assert any(e["evidence_type"] == "demo_reset" for e in evidence)
    assert (await ops.post("/api/v1/demo/agent/scenarios/nope/reset")).status_code == 404
