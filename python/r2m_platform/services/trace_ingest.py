"""SDK event ingestion: scope validation, dedup by event_id, out-of-order tolerant span correlation.

Events may arrive before their execution or parent span (background buffers, retries). Missing rows are
created as placeholders and completed when the real event lands, so nothing is silently dropped.
"""
import json
import re

import asyncpg

from ..workers import event_outbox
from .incident_detector import detect_for_event

# Matches token-like keys ("grant_token", "access_token") but not counters such as "input_tokens".
SENSITIVE_KEY = re.compile(r"password|secret|api[_-]?key|authorization|cookie|credential|private[_-]?key|bearer"
                           r"|(^|_)token$|(^|_)ssn$|card[_-]?number", re.I)
MAX_STRING = 2000
MAX_ATTRIBUTES_BYTES = 16_384


def sanitize(value, depth: int = 0):
    """Drop secret-looking keys, truncate long strings, bound nesting."""
    if depth > 5:
        return "[depth-limited]"
    if isinstance(value, dict):
        return {str(k)[:100]: ("[redacted]" if SENSITIVE_KEY.search(str(k)) else sanitize(v, depth + 1))
                for k, v in list(value.items())[:100]}
    if isinstance(value, list):
        return [sanitize(v, depth + 1) for v in value[:100]]
    if isinstance(value, str) and len(value) > MAX_STRING:
        return value[:MAX_STRING] + "…[truncated]"
    return value


def sanitize_attributes(attrs: dict) -> dict:
    clean = sanitize(attrs)
    return clean if len(json.dumps(clean, default=str)) <= MAX_ATTRIBUTES_BYTES else {"_dropped": "attributes exceeded size limit"}


async def _deployment_scope(conn, deployment_id):
    return await conn.fetchrow(
        """SELECT d.id, d.installation_id, i.agent_id, i.customer_org_id, a.vendor_org_id
           FROM deployments d JOIN agent_installations i ON i.id = d.installation_id JOIN agents a ON a.id = i.agent_id
           WHERE d.id = $1""", deployment_id)


async def ensure_execution(conn, execution_id, deployment_id, customer_org_id, trace_id, started_at) -> bool:
    """Create the execution if absent. False when the id/trace is already bound to something else."""
    try:
        await conn.execute(
            """INSERT INTO executions(id, deployment_id, customer_org_id, trace_id, status, started_at)
               VALUES ($1,$2,$3,$4,'running',$5) ON CONFLICT (id) DO NOTHING""",
            execution_id, deployment_id, customer_org_id, trace_id, started_at)
    except asyncpg.UniqueViolationError:  # trace_id reused by another execution
        return False
    row = await conn.fetchrow("SELECT deployment_id, trace_id FROM executions WHERE id=$1", execution_id)
    return row["deployment_id"] == deployment_id and row["trace_id"] == trace_id


async def _ensure_span(conn, span_id, execution_id, occurred_at) -> bool:
    await conn.execute(
        """INSERT INTO spans(id, execution_id, kind, name, status, started_at)
           VALUES ($1,$2,'unknown','(pending)','placeholder',$3) ON CONFLICT (id) DO NOTHING""",
        span_id, execution_id, occurred_at)
    return await conn.fetchval("SELECT execution_id FROM spans WHERE id=$1", span_id) == execution_id


COST_SOURCES = {"observed", "estimated", "allocated", "simulated"}


async def _apply(conn, ev, attrs) -> None:
    if ev.kind == "execution.started":
        await conn.execute(
            """UPDATE executions SET started_at = least(started_at, $2), scenario = coalesce($3, scenario),
               metadata = metadata || $4, status = 'running', ended_at = NULL WHERE id = $1""",
            ev.execution_id, ev.occurred_at, attrs.get("scenario"), attrs)
    elif ev.kind == "execution.ended":
        status = ev.status if ev.status in ("completed", "failed", "cancelled") else "completed"
        await conn.execute("UPDATE executions SET status=$2, ended_at=$3 WHERE id=$1", ev.execution_id, status, ev.occurred_at)
    elif ev.kind == "span" and ev.span_id:
        # SDK emits each span once, when it ends: occurred_at = start, duration_ms = length.
        await conn.execute(
            """UPDATE spans SET parent_span_id=$2, kind=$3, name=$4, status=$5, started_at=$6, duration_ms=$7,
               ended_at = $6::timestamptz + make_interval(secs => (coalesce($7::numeric, 0) / 1000)::float8), attributes = attributes || $8
               WHERE id=$1""",
            ev.span_id, ev.parent_span_id, ev.span_kind or "span", ev.name, ev.status or "ok", ev.occurred_at,
            ev.duration_ms, attrs)
    elif ev.kind == "usage":
        source = attrs.get("cost_source")
        await conn.execute(
            """INSERT INTO usage_records(execution_id, span_id, component_kind, input_tokens, output_tokens,
               amount_usd, cost_source, duration_ms, occurred_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            ev.execution_id, ev.span_id, str(attrs.get("component_kind", "model"))[:40],
            _int(attrs.get("input_tokens")), _int(attrs.get("output_tokens")),
            max(float(attrs.get("amount_usd") or 0), 0.0), source if source in COST_SOURCES else "estimated",
            attrs.get("duration_ms") if isinstance(attrs.get("duration_ms"), (int, float)) else ev.duration_ms,
            ev.occurred_at)


def _int(v):
    return int(v) if isinstance(v, (int, float)) and v >= 0 else None


def _component(attrs: dict) -> str | None:
    key = attrs.get("component_key") or attrs.get("component")
    return key if isinstance(key, str) else None


async def _touch(conn, installation_id, occurred_at, component: str | None) -> None:
    await conn.execute(
        "UPDATE agent_installations SET last_heartbeat_at = greatest(coalesce(last_heartbeat_at, $2), $2) WHERE id=$1",
        installation_id, occurred_at)
    if component:
        await conn.execute(
            """UPDATE agent_components SET last_seen_at = greatest(coalesce(last_seen_at, $3), $3)
               WHERE installation_id=$1 AND component_key=$2""", installation_id, component, occurred_at)


async def ingest(conn, events, principal) -> dict:
    accepted, duplicates, rejected = 0, 0, []
    scopes: dict = {}
    for ev in sorted(events, key=lambda e: e.occurred_at):
        if ev.deployment_id not in scopes:
            scopes[ev.deployment_id] = await _deployment_scope(conn, ev.deployment_id)
        scope = scopes[ev.deployment_id]
        if (not scope or (ev.vendor_org_id, ev.customer_org_id) != (principal.vendor_org_id, principal.customer_org_id)
                or scope["agent_id"] != ev.agent_id or scope["customer_org_id"] != ev.customer_org_id
                or scope["vendor_org_id"] != ev.vendor_org_id):
            rejected.append({"event_id": str(ev.event_id), "code": "scope_mismatch"})
            continue
        attrs = sanitize_attributes(ev.attributes)
        if ev.execution_id is None:
            if ev.kind != "heartbeat":
                rejected.append({"event_id": str(ev.event_id), "code": "execution_required"})
                continue
            await _touch(conn, scope["installation_id"], ev.occurred_at, _component(attrs))  # liveness only
            accepted += 1
            continue
        trace_id = ev.trace_id or ev.execution_id  # SDK default: trace_id = execution_id
        async with conn.transaction():
            if not await ensure_execution(conn, ev.execution_id, ev.deployment_id, ev.customer_org_id, trace_id, ev.occurred_at):
                rejected.append({"event_id": str(ev.event_id), "code": "execution_mismatch"})
                continue
            spans_ok = all([await _ensure_span(conn, s, ev.execution_id, ev.occurred_at)
                            for s in (ev.parent_span_id, ev.span_id) if s])
            if not spans_ok:
                rejected.append({"event_id": str(ev.event_id), "code": "span_mismatch"})
                continue
            event_attrs = {**attrs, "name": ev.name, "schema_version": ev.schema_version,
                           **({"span_kind": ev.span_kind} if ev.span_kind else {}),
                           **({"duration_ms": ev.duration_ms} if ev.duration_ms is not None else {}),
                           **({"request_id": ev.request_id} if ev.request_id else {})}
            inserted = await conn.fetchval(
                """INSERT INTO execution_events(id, execution_id, span_id, event_type, occurred_at, severity, status, attributes)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (id) DO NOTHING RETURNING id""",
                ev.event_id, ev.execution_id, ev.span_id, ev.kind, ev.occurred_at, ev.severity, ev.status, event_attrs)
            if inserted is None:
                duplicates += 1
                continue
            await _apply(conn, ev, attrs)
            await _touch(conn, scope["installation_id"], ev.occurred_at, _component(attrs))
            await detect_for_event(conn, scope["installation_id"], ev)
            await event_outbox.enqueue(conn, ev.customer_org_id, {
                "event_id": ev.event_id, "kind": ev.kind, "name": ev.name, "occurred_at": ev.occurred_at.isoformat(),
                "deployment_id": str(ev.deployment_id), "execution_id": str(ev.execution_id),
                "severity": ev.severity, "status": ev.status, "attributes": attrs})
            accepted += 1
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}
