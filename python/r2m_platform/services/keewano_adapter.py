"""Keewano adapter (AI-owned): typed event mapping, REST ingestion and MCP history queries.

Keewano is optional, advisory analytics. Nothing here can authorize an action. The outbox worker
(workers/event_outbox.py) owns durability, retry and dead-lettering; this module owns:

- ``map_event(event) -> dict | None``: pure, allowlisted mapping to typed events (ids >= 2000).
  Only enumerated values and numbers are forwarded: no prompts, logs, model text or raw ids.
- ``async send_events(payloads)``: registers the custom event types once, then posts each
  incident stream to the REST ingress. Raises on any failure so the outbox retries.
- ``async query(question, context)``: asks Keewano (MCP, SQL tool discovered at runtime via
  ``tools/list``) which remediation category historically preceded recovery. Returns counts plus
  ``sample_count``; the agent decides whether that evidence is strong enough.

Entity model: one Keewano entity ("install"/user stream) per R2M execution, keyed by a UUIDv5 of
the execution id, so tenant and customer identifiers are never sent in the clear.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import uuid
import zlib
from datetime import datetime, timezone
from typing import Any

import httpx

ENTITY_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://r2m.demo/keewano")

# Frozen once registered with Keewano: types are append-only, never change an existing id.
EVENT_TYPES = [
    {"eventTypeId": 2000, "name": "DeploymentVersion", "dataType": "string"},
    {"eventTypeId": 2001, "name": "IncidentCategory", "dataType": "string"},
    {"eventTypeId": 2002, "name": "RemediationProposed", "dataType": "string"},
    {"eventTypeId": 2003, "name": "RemediationSucceeded", "dataType": "bool"},
    {"eventTypeId": 2004, "name": "PolicyOutcome", "dataType": "string"},
    {"eventTypeId": 2005, "name": "ToolFailureClass", "dataType": "string"},
    {"eventTypeId": 2006, "name": "ExecutionLatencyMs", "dataType": "uint"},
    {"eventTypeId": 2007, "name": "BuildEvaluationPassed", "dataType": "bool"},
    {"eventTypeId": 2008, "name": "RecommendationSource", "dataType": "string"},
]
_TYPES = {e["eventTypeId"]: e for e in EVENT_TYPES}
CUSTOM_EVENTS_HASH = zlib.crc32(json.dumps(EVENT_TYPES, sort_keys=True).encode()) or 1

REMEDIATIONS = {"rollback_deployment": "rollback", "restart_service": "restart", "scale_instances": "scale"}
INCIDENT_CATEGORIES = ("post_deploy_errors", "capacity_pressure", "unknown")
RECOMMENDATION_SOURCES = ("keewano", "deterministic", "llm", "user")
POLICY_OUTCOMES = {"ALLOW": "allow", "DENY": "deny", "REQUIRE_APPROVAL": "approval_required"}
_VERSION = re.compile(r"^v\d+\.\d+(\.\d+)?$")
_MAX_UINT = 2**32 - 1
_transport: httpx.AsyncBaseTransport | None = None  # tests only


# ---- mapping (pure) ------------------------------------------------------
def entity_id(execution_id: str) -> str:
    return str(uuid.uuid5(ENTITY_NS, f"execution:{execution_id}"))


def _epoch(value: Any) -> int | None:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _ev(type_id: int, data: Any, ts: int | None) -> dict[str, Any]:
    e = {"eventTypeId": type_id, "dataType": _TYPES[type_id]["dataType"], "data": data}
    if ts is not None:
        e["timestamp"] = ts
    return e


def _failure_class(error_class: str) -> str:
    e = error_class.lower()
    if "timeout" in e:
        return "timeout"
    if "permission" in e or "denied" in e or "forbidden" in e:
        return "permission"
    if "refused" in e:
        return "refused"
    return "error"


def _policy_outcome(event: dict[str, Any], attrs: dict[str, Any]) -> str | None:
    # Ingest sanitizing redacts keys containing "authorization", so fall back to the event status
    # (the SDK sets it to the lower-cased outcome: allow / deny / require_approval).
    outcome = attrs.get("authorization_outcome")
    if outcome in POLICY_OUTCOMES:
        return POLICY_OUTCOMES[outcome]
    status = str(event.get("status") or "").upper()
    return POLICY_OUTCOMES.get(status)


def map_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Map one ingested R2M event to ``{"install_id", "events": [...]}`` or ``None`` to skip."""
    execution_id = event.get("execution_id")
    if not execution_id:
        return None
    kind, name = event.get("kind"), str(event.get("name") or "")
    attrs = event.get("attributes") if isinstance(event.get("attributes"), dict) else {}
    ts = _epoch(event.get("occurred_at"))
    version = attrs.get("deployment_version")
    version = version if isinstance(version, str) and _VERSION.match(version) else None
    category = attrs.get("category") if attrs.get("category") in INCIDENT_CATEGORIES else None
    remediation = REMEDIATIONS.get(attrs.get("tool"))
    out: list[dict[str, Any]] = []

    if kind == "span" and name == "step:DIAGNOSE" and category:
        if version:
            out.append(_ev(2000, version, ts))
        out.append(_ev(2001, category, ts))
    elif kind == "span" and name == "step:PROPOSE" and remediation:
        out.append(_ev(2002, remediation, ts))
        # Also at propose time, so runs that stop at approval or denial still say where the fix came from.
        if attrs.get("source") in RECOMMENDATION_SOURCES:
            out.append(_ev(2008, attrs["source"], ts))
    elif kind == "span" and name == "step:VERIFY" and remediation and isinstance(attrs.get("recovered"), bool):
        # The complete outcome record, in order, so the query never depends on same-second ordering.
        if version:
            out.append(_ev(2000, version, ts))
        if category:
            out.append(_ev(2001, category, ts))
        out.append(_ev(2002, remediation, ts))
        if attrs.get("recommendation_source") in RECOMMENDATION_SOURCES:
            out.append(_ev(2008, attrs["recommendation_source"], ts))
        out.append(_ev(2003, attrs["recovered"], ts))
    elif kind == "span" and name.startswith("tool:") and isinstance(event.get("duration_ms"), (int, float)):
        out.append(_ev(2006, max(0, min(int(event["duration_ms"]), _MAX_UINT)), ts))
    elif kind == "policy.decision" and _policy_outcome(event, attrs):
        out.append(_ev(2004, _policy_outcome(event, attrs), ts))
    elif kind == "tool.call" and isinstance(attrs.get("error_class"), str) and attrs["error_class"]:
        out.append(_ev(2005, _failure_class(attrs["error_class"]), ts))
    if not out:
        return None
    return {"install_id": entity_id(str(execution_id)), "events": out}


# ---- ingestion -----------------------------------------------------------
def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, "").strip() or default
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


_registered = False


async def register_event_types(http: httpx.AsyncClient) -> None:
    global _registered
    if _registered:
        return
    resp = await http.post(_env("KEEWANO_REGISTER_URL", "https://api.keewano.com/event/ingress/v1/json/custom"),
                           json={"customEventsHash": CUSTOM_EVENTS_HASH, "eventTypes": EVENT_TYPES})
    resp.raise_for_status()
    _registered = True


def ingest_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10, transport=_transport, headers={"k-token": _env("KEEWANO_API_KEY"),
                                                                       "Content-Type": "application/json"})


async def post_stream(http: httpx.AsyncClient, install_id: str, events: list[dict[str, Any]]) -> None:
    resp = await http.post(_env("KEEWANO_INGEST_URL", "https://api.keewano.com/event/ingress/v1/json/in"), json={
        "dataSessionId": str(uuid.uuid4()), "batch": 1, "customEventsHash": CUSTOM_EVENTS_HASH,
        "installId": install_id, "events": events})
    resp.raise_for_status()


async def send_events(payloads: list[dict[str, Any]]) -> None:
    """Group by entity (order preserved) and post one request per incident stream. Raises on failure."""
    streams: dict[str, list[dict[str, Any]]] = {}
    for p in payloads:
        if isinstance(p, str):  # payload may arrive JSON-encoded from the outbox column
            p = json.loads(p)
        streams.setdefault(p["install_id"], []).extend(p["events"])
    if not streams:
        return
    async with ingest_client() as http:
        await register_event_types(http)
        for install_id, events in streams.items():
            await post_stream(http, install_id, sorted(events, key=lambda e: e.get("timestamp", 0)))


# ---- MCP query -----------------------------------------------------------
class McpError(RuntimeError):
    pass


class McpSession:
    """Minimal MCP Streamable-HTTP client: initialize, tools/list, tools/call."""

    PROTOCOL = "2025-06-18"

    def __init__(self, url: str, token: str, timeout: float = 15.0):
        self._url = url
        self._http = httpx.AsyncClient(timeout=timeout, transport=_transport, headers={
            "k-token": token, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        self._session: str | None = None
        self._id = 0

    async def __aenter__(self) -> "McpSession":
        await self.rpc("initialize", {"protocolVersion": self.PROTOCOL, "capabilities": {},
                                      "clientInfo": {"name": "r2m-keewano-adapter", "version": "0.1.0"}})
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._http.aclose()

    @property
    def session_id(self) -> str | None:
        return self._session

    async def _post(self, message: dict[str, Any]) -> httpx.Response:
        headers = {"Mcp-Session-Id": self._session} if self._session else {}
        if self._session:
            headers["MCP-Protocol-Version"] = self.PROTOCOL
        resp = await self._http.post(self._url, json=message, headers=headers)
        if resp.status_code >= 400:
            raise McpError(f"MCP {message.get('method')} -> HTTP {resp.status_code}")
        self._session = resp.headers.get("mcp-session-id", self._session)
        return resp

    async def rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._id += 1
        resp = await self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        for msg in _messages(resp):
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise McpError(f"MCP {method} error {msg['error'].get('code')}")
                return msg.get("result") or {}
        raise McpError(f"MCP {method}: no response")


def _messages(resp: httpx.Response) -> list[dict[str, Any]]:
    if "text/event-stream" in resp.headers.get("content-type", ""):
        out = []
        for block in resp.text.split("\n\n"):
            data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
            if data:
                try:
                    out.append(json.loads(data))
                except json.JSONDecodeError:
                    continue
        return out
    body = resp.json() if resp.content else {}
    return body if isinstance(body, list) else [body]


def project_id_hint() -> str | None:
    """KEEWANO_PROJECT_ID, else the projectId claim of the project SDK key (a public identifier, not a secret)."""
    explicit = os.environ.get("KEEWANO_PROJECT_ID", "").strip()
    if explicit:
        return explicit
    parts = os.environ.get("KEEWANO_API_KEY", "").split(".")
    if len(parts) == 3:
        try:
            pad = "=" * (-len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
            pid = claims.get("projectId")
            return str(pid) if pid else None
        except (ValueError, json.JSONDecodeError):
            return None
    return None


def pick_sql_tool(tools: list[dict[str, Any]], project_id: str | None = None) -> tuple[str, str, dict[str, Any]]:
    """Choose the SQL tool and its query argument from ``tools/list``. Never guesses a tool name.

    Tools with "sql" in their *name* win over ones that only mention SQL in the description.
    """
    ranked = sorted(tools, key=lambda t: ("sql" not in str(t.get("name", "")).lower(),
                                          "sql" not in str(t.get("description", "")).lower()))
    for t in ranked:
        text = f"{t.get('name', '')} {t.get('description', '')}".lower()
        if "sql" not in text:
            continue
        schema = t.get("inputSchema") or {}
        props = schema.get("properties") or {}
        query_arg = next((k for k in ("sqlQuery", "sql", "query", "statement", "q") if k in props), None)
        if query_arg is None:
            continue
        extra: dict[str, Any] = {}
        for req in schema.get("required") or []:
            if req == query_arg:
                continue
            if "project" in req.lower() and project_id:
                extra[req] = project_id
            else:
                raise McpError(f"SQL tool {t.get('name')} requires unsupported argument {req!r}")
        if "maxRows" in props:
            extra.setdefault("maxRows", 200)
        return t["name"], query_arg, extra
    raise McpError("no SQL tool offered by the Keewano MCP server")


async def _project_id(mcp: "McpSession", tools: list[dict[str, Any]]) -> str | None:
    pid = project_id_hint()
    if pid or not any(t.get("name") == "list_projects" for t in tools):
        return pid
    result = await mcp.rpc("tools/call", {"name": "list_projects", "arguments": {}})
    rows = parse_rows(list(result.get("content") or []))
    ids = [r.get("id") or r.get("projectId") for r in rows if r.get("id") or r.get("projectId")]
    return str(ids[0]) if len(ids) == 1 else None


def history_sql(category: str) -> str:
    if category not in INCIDENT_CATEGORIES:
        raise ValueError("unsupported incident category")
    # Each incident stream carries one outcome record; values carry forward, so rows with an outcome
    # hold the category and remediation of that incident.
    return ('SELECT "RemediationProposed" AS remediation, "RemediationSucceeded" AS succeeded, '
            'count(DISTINCT user_id) AS incidents FROM events '
            f"WHERE \"IncidentCategory\" = '{category}' AND \"RemediationSucceeded\" IS NOT NULL "
            "GROUP BY remediation, succeeded")


def before_after_sql() -> str:
    """Bonus measurement in Keewano itself: recovery by recommendation source (Keewano-informed vs not)."""
    return ('SELECT "RecommendationSource" AS source, "RemediationSucceeded" AS succeeded, '
            'count(DISTINCT user_id) AS incidents FROM events '
            'WHERE "RemediationSucceeded" IS NOT NULL GROUP BY source, succeeded')


async def run_sql(sql: str) -> tuple[str, list[dict[str, Any]]]:
    """Run one read-only SQL statement through the discovered MCP SQL tool. Returns (tool, rows)."""
    async with McpSession(_env("KEEWANO_MCP_URL", "https://api.keewano.com/mcp"), _env("KEEWANO_PAT")) as mcp:
        tools = (await mcp.rpc("tools/list", {})).get("tools") or []
        tool, arg, extra = pick_sql_tool(tools, await _project_id(mcp, tools))
        result = await mcp.rpc("tools/call", {"name": tool, "arguments": {arg: sql, **extra}})
    if result.get("isError"):
        detail = parse_text(result)[:300]
        raise McpError(f"Keewano tool {tool} returned an error: {detail}")
    content = list(result.get("content") or [])
    if result.get("structuredContent") is not None:
        content.append({"type": "structured", "structuredContent": result["structuredContent"]})
    return tool, parse_rows(content)


_RESULT_SUMMARY = re.compile(r"\brow\(s\)", re.I)


def parse_text(result: dict[str, Any]) -> str:
    return "\n".join(c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict))


def parse_rows(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows from a tool result: JSON (list / {rows|data|result}) or a CSV / markdown table."""
    text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text").strip()
    for c in content:
        if isinstance(c, dict) and isinstance(c.get("structuredContent"), (list, dict)):
            text = json.dumps(c["structuredContent"])
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        data = None
    if isinstance(data, dict):
        cols = data.get("columns")
        data = next((data[k] for k in ("rows", "data", "result", "results") if k in data), data)
        if cols and isinstance(data, list) and data and isinstance(data[0], list):
            names = [c if isinstance(c, str) else c.get("name") for c in cols]
            data = [dict(zip(names, r)) for r in data]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not set(ln.strip()) <= set("|-: +")]
    # run_sql_query prefixes its CSV with "SQL result for project <id>: N row(s), M column(s)."
    summary = next((i for i, ln in enumerate(lines) if _RESULT_SUMMARY.search(ln)), None)
    if summary is not None:
        lines = lines[summary + 1:]
    if not lines:
        return []
    if "|" in lines[0]:
        rows = [[cell.strip() for cell in ln.strip("|").split("|")] for ln in lines]
    else:
        rows = list(csv.reader(io.StringIO("\n".join(lines))))
    header = [h.strip().lower() for h in rows[0]]
    return [dict(zip(header, r)) for r in rows[1:]]


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in ("true", "t", "1", "yes")


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, dict[str, int]] = {}
    for row in rows:
        r = {str(k).lower(): v for k, v in row.items()}
        name = str(r.get("remediation", "")).strip().lower()
        if name not in REMEDIATIONS.values():
            continue  # untrusted output: ignore anything that isn't a known category
        try:
            n = max(0, int(float(r.get("incidents", 0))))
        except (TypeError, ValueError):
            continue
        slot = by.setdefault(name, {"samples": 0, "successes": 0})
        slot["samples"] += n
        if _truthy(r.get("succeeded")):
            slot["successes"] += n
    return [{"remediation": k, **v} for k, v in sorted(by.items())]


_CATEGORY_IN_QUESTION = re.compile(r"category\s+([a-z_]+)")


async def query(question: str, context: dict[str, Any]) -> dict[str, Any]:
    category = context.get("incident_category")
    if category not in INCIDENT_CATEGORIES:
        m = _CATEGORY_IN_QUESTION.search(question or "")
        category = m.group(1) if m and m.group(1) in INCIDENT_CATEGORIES else "post_deploy_errors"
    sql = history_sql(category)
    tool, rows = await run_sql(sql)
    recommendations = aggregate(rows)
    total = sum(r["samples"] for r in recommendations)
    return {"sample_count": total, "category": category, "recommendations": recommendations, "tool": tool,
            "query": sql,
            "summary": ", ".join(f"{r['remediation']} {r['successes']}/{r['samples']} recovered"
                                 for r in recommendations) or "no matching history"}
