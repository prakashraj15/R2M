import base64
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ..auth import Actor, agent_installations, installation_in_scope
from ..dependencies import actor, db
from ..errors import ApiError, not_found

router = APIRouter(tags=["traces"])
VENDOR_PRIVATE_PREFIXES = ("prompt", "completion", "system_prompt", "vendor_")


def _encode(started_at: datetime, id_: UUID) -> str:
    return base64.urlsafe_b64encode(f"{started_at.isoformat()}|{id_}".encode()).decode()


def _decode(cursor: str):
    try:
        ts, id_ = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(ts), UUID(id_)
    except ValueError:
        raise ApiError(400, "invalid_cursor", "cursor is malformed")


@router.get("/agents/{agent_id}/traces")
async def traces(agent_id: UUID, installation_id: UUID | None = None, limit: int = Query(50, ge=1, le=200),
                 cursor: str | None = None, a: Actor = Depends(actor), conn=Depends(db)):
    ids = [i["id"] for i in await agent_installations(conn, a, agent_id, installation_id)]
    after = _decode(cursor) if cursor else (None, None)
    rows = await conn.fetch(
        """SELECT e.id AS execution_id, e.trace_id, e.status, e.started_at, e.ended_at, e.scenario, d.installation_id,
                  b.version AS build_version,
                  (SELECT count(*) FROM spans s WHERE s.execution_id = e.id AND s.status <> 'placeholder') AS span_count,
                  (SELECT count(*) FROM policy_decisions p WHERE p.execution_id = e.id) AS decision_count,
                  (SELECT coalesce(sum(amount_usd), 0) FROM usage_records u WHERE u.execution_id = e.id) AS cost_usd
           FROM executions e JOIN deployments d ON d.id = e.deployment_id JOIN builds b ON b.id = d.build_id
           WHERE d.installation_id = ANY($1::uuid[])
             AND ($2::timestamptz IS NULL OR (e.started_at, e.id) < ($2, $3))
           ORDER BY e.started_at DESC, e.id DESC LIMIT $4""", ids, after[0], after[1], limit)
    nxt = _encode(rows[-1]["started_at"], rows[-1]["execution_id"]) if len(rows) == limit else None
    return {"traces": [{**dict(r), "cost_usd": float(r["cost_usd"])} for r in rows], "next_cursor": nxt}


def _redact(attrs: dict, vendor_view: bool) -> dict:
    if vendor_view or not isinstance(attrs, dict):
        return attrs
    return {k: ("[vendor-private]" if k.lower().startswith(VENDOR_PRIVATE_PREFIXES) else v) for k, v in attrs.items()}


@router.get("/traces/{trace_id}")
async def trace(trace_id: UUID, a: Actor = Depends(actor), conn=Depends(db)):
    ex = await conn.fetchrow(
        """SELECT e.*, d.installation_id, b.version AS build_version FROM executions e
           JOIN deployments d ON d.id = e.deployment_id JOIN builds b ON b.id = d.build_id WHERE e.trace_id=$1""", trace_id)
    if not ex:
        raise not_found("trace")
    inst = await installation_in_scope(conn, a, ex["installation_id"])
    vendor_view = inst["vendor_org_id"] in a.org_ids
    spans = [dict(s) for s in await conn.fetch(
        "SELECT * FROM spans WHERE execution_id=$1 ORDER BY started_at, id", ex["id"])]
    by_id = {s["id"]: s for s in spans}
    for s in spans:  # depth for the waterfall; orphans (parent never arrived) render at the root
        depth, p, seen = 0, s["parent_span_id"], set()
        while p in by_id and p not in seen:
            seen.add(p)
            depth, p = depth + 1, by_id[p]["parent_span_id"]
        s["depth"] = depth
        s["attributes"] = _redact(s["attributes"], vendor_view)
    events = await conn.fetch("SELECT * FROM execution_events WHERE execution_id=$1 ORDER BY occurred_at", ex["id"])
    actions = await conn.fetch("SELECT * FROM tool_actions WHERE execution_id=$1 ORDER BY requested_at", ex["id"])
    decisions = await conn.fetch(
        """SELECT pd.*, r.policy_key, r.version AS policy_version, r.artifact_hash FROM policy_decisions pd
           LEFT JOIN policy_revisions r ON r.id = pd.revision_id WHERE pd.execution_id=$1 ORDER BY pd.evaluated_at""", ex["id"])
    grants = await conn.fetch(
        """SELECT id, action_id, tool_key, arguments_hash, issued_at, expires_at, applied_at, consumed_at, policy_revision_ids
           FROM action_grants WHERE execution_id=$1""", ex["id"])
    approvals = await conn.fetch(
        """SELECT ra.id, ra.action_id, ra.status, ra.requested_at, ra.decided_at, u.email AS reviewer
           FROM runtime_approvals ra JOIN tool_actions t ON t.id = ra.action_id LEFT JOIN users u ON u.id = ra.reviewer_id
           WHERE t.execution_id=$1""", ex["id"])
    usage = await conn.fetch("SELECT * FROM usage_records WHERE execution_id=$1 ORDER BY occurred_at", ex["id"])
    insights = await conn.fetch(
        "SELECT id, provider, prompt_summary, status, sample_count, response_summary, created_at FROM insight_queries WHERE execution_id=$1",
        ex["id"])
    return {"execution": {**dict(ex), "metadata": _redact(ex["metadata"], vendor_view)},
            "spans": spans,
            "events": [{**dict(e), "attributes": _redact(e["attributes"], vendor_view)} for e in events],
            "actions": [dict(x) for x in actions], "decisions": [dict(x) for x in decisions],
            "grants": [dict(x) for x in grants], "approvals": [dict(x) for x in approvals],
            "usage": [{**dict(u), "amount_usd": float(u["amount_usd"])} for u in usage],
            "insights": [dict(x) for x in insights], "redacted_for_customer": not vendor_view}
