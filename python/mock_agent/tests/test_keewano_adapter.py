"""The Keewano loop is one AI-owned feature: agent insight handling + the platform adapter."""
import asyncio
import functools
import json

import httpx
import pytest

from mock_agent.insights import interpret
from mock_agent.sandbox import Sandbox
from r2m_platform.services import keewano_adapter as k


def run_async(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


@pytest.fixture(autouse=True)
def keewano_env(monkeypatch):
    monkeypatch.setenv("KEEWANO_API_KEY", "test-api-key")
    monkeypatch.setenv("KEEWANO_PAT", "test-pat")
    monkeypatch.setattr(k, "_registered", False)
    yield
    monkeypatch.setattr(k, "_transport", None)


def _event(kind, name, **attrs):
    return {"event_id": "e1", "kind": kind, "name": name, "occurred_at": "2026-10-11T12:00:00Z",
            "execution_id": "11111111-1111-4111-8111-111111111111", "attributes": attrs}


def test_map_event_allowlists_and_sanitizes():
    verify = k.map_event(_event("span", "step:VERIFY", tool="rollback_deployment", recovered=True,
                                category="post_deploy_errors", deployment_version="v2.1"))
    assert [e["eventTypeId"] for e in verify["events"]] == [2000, 2001, 2002, 2003]
    assert verify["events"][2]["data"] == "rollback" and verify["events"][3]["data"] is True
    sourced = k.map_event(_event("span", "step:VERIFY", tool="restart_service", recovered=False,
                                 recommendation_source="keewano"))
    assert [(e["eventTypeId"], e["data"]) for e in sourced["events"]] == [(2002, "restart"), (2008, "keewano"),
                                                                          (2003, False)]
    assert verify["install_id"] == k.entity_id("11111111-1111-4111-8111-111111111111")
    assert k.map_event(_event("policy.decision", "p", authorization_outcome="REQUIRE_APPROVAL"))["events"][0]["data"] \
        == "approval_required"
    assert k.map_event(_event("tool.call", "t", error_class="TimeoutError"))["events"][0]["data"] == "timeout"
    # Free text, unknown values and missing execution never leave R2M.
    assert k.map_event(_event("span", "step:DIAGNOSE", category="drop table; --")) is None
    assert k.map_event(_event("span", "step:DIAGNOSE", category="post_deploy_errors",
                              deployment_version="v2.1 ; customer jane@x.com"))["events"] == [
        {"eventTypeId": 2001, "dataType": "string", "data": "post_deploy_errors", "timestamp": k._epoch("2026-10-11T12:00:00Z")}]
    assert k.map_event(_event("insight", "keewano", summary="anything")) is None
    assert k.map_event({**_event("span", "step:PROPOSE", tool="restart_service"), "execution_id": None}) is None
    proposed = k.map_event(_event("span", "step:PROPOSE", tool="rollback_deployment", source="keewano"))
    assert [(e["eventTypeId"], e["data"]) for e in proposed["events"]] == [(2002, "rollback"), (2008, "keewano")]
    assert [e["eventTypeId"] for e in k.map_event(_event("span", "step:PROPOSE", tool="rollback_deployment",
                                                         source="fault_injection"))["events"]] == [2002]


def test_agent_run_maps_to_complete_outcome_record():
    sb = Sandbox("degraded")
    sb.say("fix it")
    mapped = [m for e in sorted(sb.platform.events.values(), key=lambda e: e["occurred_at"]) if (m := k.map_event(e))]
    names = [ev["eventTypeId"] for m in mapped for ev in m["events"]]
    assert 2001 in names and 2002 in names and 2003 in names
    outcome = next(m for m in mapped if any(ev["eventTypeId"] == 2003 for ev in m["events"]))
    assert [ev["data"] for ev in outcome["events"]] == ["v2.1", "post_deploy_errors", "restart", "deterministic", False]
    assert len({m["install_id"] for m in mapped}) == 1


@run_async
async def test_send_events_registers_once_and_posts_per_stream():
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.url.path, request.headers["k-token"], json.loads(request.content)))
        return httpx.Response(200, json={})

    k._transport = httpx.MockTransport(handler)
    a = {"install_id": "a", "events": [k._ev(2002, "restart", 2), k._ev(2001, "unknown", 1)]}
    b = {"install_id": "b", "events": [k._ev(2003, True, 5)]}
    await k.send_events([a, json.dumps(b)])
    await k.send_events([a])
    paths = [c[0] for c in calls]
    assert paths.count("/event/ingress/v1/json/custom") == 1
    assert paths.count("/event/ingress/v1/json/in") == 3
    body = calls[1][2]
    assert body["installId"] == "a" and body["customEventsHash"] == k.CUSTOM_EVENTS_HASH
    assert [e["timestamp"] for e in body["events"]] == [1, 2]  # time-ordered
    assert all(c[1] == "test-api-key" for c in calls)


@run_async
async def test_send_events_raises_for_outbox_retry():
    k._transport = httpx.MockTransport(lambda r: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await k.send_events([{"install_id": "a", "events": [k._ev(2003, True, 1)]}])


def _mcp_server(rows_text: str, *, sse: bool = False, tools=None):
    seen = {"sql": None, "session": []}
    tools = tools if tools is not None else [
        {"name": "lua_query", "description": "Run a Lua script", "inputSchema": {"properties": {"script": {"type": "string"}}}},
        {"name": "run_query", "description": "Execute a read-only SQL query over events",
         "inputSchema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}}]

    def handler(request: httpx.Request):
        assert request.headers["k-token"] == "test-pat"
        msg = json.loads(request.content)
        seen["session"].append(request.headers.get("mcp-session-id"))
        if "id" not in msg:
            return httpx.Response(202)
        if msg["method"] == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "kw"}}
        elif msg["method"] == "tools/list":
            result = {"tools": tools}
        else:
            seen["sql"] = msg["params"]["arguments"]
            result = {"content": [{"type": "text", "text": rows_text}], "isError": False}
        payload = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        if sse:
            return httpx.Response(200, text=f"event: message\ndata: {json.dumps(payload)}\n\n",
                                  headers={"content-type": "text/event-stream", "mcp-session-id": "s-1"})
        return httpx.Response(200, json=payload, headers={"mcp-session-id": "s-1"})

    return handler, seen


ROWS = [{"remediation": "rollback", "succeeded": True, "incidents": 35},
        {"remediation": "rollback", "succeeded": False, "incidents": 3},
        {"remediation": "restart", "succeeded": True, "incidents": 4},
        {"remediation": "restart", "succeeded": False, "incidents": 15},
        {"remediation": "rm -rf", "succeeded": True, "incidents": 500}]


@pytest.mark.parametrize("sse", [False, True])
@run_async
async def test_query_discovers_sql_tool_and_aggregates(sse):
    handler, seen = _mcp_server(json.dumps(ROWS), sse=sse)
    k._transport = httpx.MockTransport(handler)
    q = "For incidents of category post_deploy_errors on payments-api after deployment v2.1, which remediation..."
    result = await k.query(q, {"installation_id": "x"})
    assert set(seen["sql"]) == {"sql"} and "'post_deploy_errors'" in seen["sql"]["sql"]
    assert seen["session"][-1] == "s-1"
    assert result["sample_count"] == 57 and result["tool"] == "run_query"
    assert result["recommendations"] == [{"remediation": "restart", "samples": 19, "successes": 4},
                                         {"remediation": "rollback", "samples": 38, "successes": 35}]
    # The agent turns this into a Keewano-informed rollback proposal.
    insight = interpret({"status": "ok", "insight_id": "q1", "result": result})
    assert insight.supported and insight.best.remediation == "rollback"


@run_async
async def test_query_parses_markdown_table_results():
    table = ("| remediation | succeeded | incidents |\n|---|---|---|\n| scale | true | 24 |\n| scale | false | 6 |\n"
             "| restart | true | 5 |")
    handler, _ = _mcp_server(table)
    k._transport = httpx.MockTransport(handler)
    result = await k.query("category capacity_pressure", {})
    assert result["category"] == "capacity_pressure"
    assert result["recommendations"][1] == {"remediation": "scale", "samples": 30, "successes": 24}


@run_async
async def test_query_without_sql_tool_fails_cleanly():
    handler, _ = _mcp_server("[]", tools=[{"name": "lua_query", "description": "Lua",
                                           "inputSchema": {"properties": {"script": {"type": "string"}}}}])
    k._transport = httpx.MockTransport(handler)
    with pytest.raises(k.McpError):
        await k.query("category post_deploy_errors", {})


def test_history_sql_rejects_unknown_category():
    with pytest.raises(ValueError):
        k.history_sql("x' OR 1=1 --")


def test_parse_rows_handles_live_run_sql_query_format():
    text = ("SQL result for project 963f3689-fab3-4264-ad2f-ea3e2178d690: 3 row(s), 3 column(s).\n"
            "remediation,succeeded,incidents\nrollback,true,53\nrollback,false,5\nrestart,true,8\n")
    rows = k.parse_rows([{"type": "text", "text": text}])
    assert rows[0] == {"remediation": "rollback", "succeeded": "true", "incidents": "53"}
    assert k.aggregate(rows) == [{"remediation": "restart", "samples": 8, "successes": 8},
                                 {"remediation": "rollback", "samples": 58, "successes": 53}]
    empty = "SQL result for project x: 0 row(s), 2 column(s).\nc,n\n"
    assert k.parse_rows([{"type": "text", "text": empty}]) == []


def test_live_tool_schema_is_picked_by_name():
    tools = [{"name": "get_tool_guide", "description": "reference incl. SQL", "inputSchema": {
                 "properties": {"tool": {"type": "string"}}, "required": ["tool"]}},
             {"name": "run_sql_query", "description": "Run a SQL query", "inputSchema": {
                 "properties": {"projectId": {"type": "string"}, "sqlQuery": {"type": "string"},
                                "maxRows": {"type": "integer"}}, "required": ["projectId", "sqlQuery"]}}]
    assert k.pick_sql_tool(tools, "p-1") == ("run_sql_query", "sqlQuery", {"projectId": "p-1", "maxRows": 200})
