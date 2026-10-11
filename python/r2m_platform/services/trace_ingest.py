"""SDK event ingestion: scope validation, dedup by event_id, out-of-order tolerant span correlation.

Events may arrive before their execution or parent span (background buffers, retries). Missing rows are
created as placeholders and completed when the real event lands, so nothing is silently dropped.
"""
import json
import re

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


COST_SOURCES = {"observed", "estimated", "allocated", "simulated"}


def _int(v):
    return int(v) if isinstance(v, (int, float)) and v >= 0 else None


def _shape(ev) -> dict:
    """Everything that must stay in Python (sanitizing, derived fields), so the DB function stays dumb."""
    attrs = sanitize_attributes(ev.attributes)
    d = ev.model_dump(mode="json")
    d["attributes"] = attrs
    d["_event_attrs"] = {**attrs, "name": ev.name, "schema_version": ev.schema_version,
                         **({"span_kind": ev.span_kind} if ev.span_kind else {}),
                         **({"duration_ms": ev.duration_ms} if ev.duration_ms is not None else {}),
                         **({"request_id": ev.request_id} if ev.request_id else {})}
    component = attrs.get("component_key") or attrs.get("component")
    d["_component"] = component if isinstance(component, str) else None
    if ev.kind == "usage":
        source = attrs.get("cost_source")
        d["_usage"] = {
            "component_kind": str(attrs.get("component_kind", "model"))[:40],
            "input_tokens": _int(attrs.get("input_tokens")), "output_tokens": _int(attrs.get("output_tokens")),
            "amount_usd": max(float(attrs.get("amount_usd") or 0), 0.0),
            "cost_source": source if source in COST_SOURCES else "estimated",
            "duration_ms": attrs.get("duration_ms") if isinstance(attrs.get("duration_ms"), (int, float)) else ev.duration_ms}
    return d


async def ingest(conn, events, principal) -> dict:
    """One round trip for the whole batch (db function r2m_ingest_batch), then incidents and the Keewano outbox
    for accepted events. Per-event subtransactions in the DB keep one bad event from losing the batch."""
    shaped = [_shape(ev) for ev in events]
    if not event_outbox.mirroring_enabled():
        return await _ingest(conn, events, shaped, principal, mirror=False)
    async with conn.transaction():  # outbox rows commit atomically with their events
        return await _ingest(conn, events, shaped, principal, mirror=True)


async def _ingest(conn, events, shaped, principal, mirror: bool) -> dict:
    rows = await conn.fetch("SELECT * FROM r2m_ingest_batch($1, $2, $3)",
                            principal.vendor_org_id, principal.customer_org_id, shaped)
    installation = {r["event_id"]: r["installation_id"] for r in rows if r["outcome"] == "accepted"}
    accepted = [(ev, d) for ev, d in zip(events, shaped) if ev.event_id in installation and ev.execution_id]
    for ev, _ in accepted:  # only touches the DB when a rule actually fires
        await detect_for_event(conn, installation[ev.event_id], ev)
    if mirror and accepted:
        await event_outbox.enqueue_many(conn, principal.customer_org_id, [
            {"event_id": ev.event_id, "kind": ev.kind, "name": ev.name, "occurred_at": ev.occurred_at.isoformat(),
             "deployment_id": str(ev.deployment_id), "execution_id": str(ev.execution_id), "severity": ev.severity,
             "status": ev.status, "attributes": d["attributes"]} for ev, d in accepted])
    return {"accepted": sum(r["outcome"] == "accepted" for r in rows),
            "duplicates": sum(r["outcome"] == "duplicate" for r in rows),
            "rejected": [{"event_id": str(r["event_id"]), "code": r["outcome"]} for r in rows
                         if r["outcome"] not in ("accepted", "duplicate")]}
