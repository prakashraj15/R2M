"""Agent registry, deployments and topology for scoped installations."""
from uuid import UUID

import asyncpg

from ..errors import ApiError, conflict
from . import metrics_rollup


async def register_from_sdk(conn, body, principal) -> dict:
    """SDK_CONTRACT §1, in one database round trip (db function r2m_register_sdk_agent). A newly seen build gets a
    *proposed* deployment: only the release gate (evaluate + deploy) can make it deployed, so registering code
    never bypasses evaluation or approval."""
    if (body.vendor_org_id, body.customer_org_id) != (principal.vendor_org_id, principal.customer_org_id):
        raise ApiError(403, "tenant_scope_invalid", "SDK token is not scoped to this vendor/customer pair")
    b = body.build
    try:
        row = await conn.fetchrow(
            "SELECT * FROM r2m_register_sdk_agent($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)",
            body.vendor_org_id, body.customer_org_id, body.environment, body.slug, body.name, body.description,
            body.sdk_version, b.version, b.source_digest, b.artifact_digest,
            [c.model_dump() for c in body.topology.components], [e.model_dump() for e in body.topology.edges])
    except asyncpg.PostgresError as exc:
        if exc.sqlstate == "R2M10":
            raise conflict("artifact digest already registered under another version")
        if exc.sqlstate == "R2M11":
            raise ApiError(422, "validation_error", "topology edges reference unknown components")
        raise
    if not row:
        raise ApiError(403, "tenant_scope_invalid", "vendor is not actively linked to this customer")
    return dict(row)


async def list_agents(conn, installations: list[dict]) -> list[dict]:
    if not installations:
        return []
    ids = [i["id"] for i in installations]
    rows = await conn.fetch(
        """SELECT a.id AS agent_id, a.slug, a.name, a.description, a.vendor_org_id, vo.name AS vendor_name,
                  i.id AS installation_id, i.customer_org_id, co.name AS customer_name, i.environment, i.last_heartbeat_at,
                  d.id AS deployment_id, d.status AS deployment_status, b.version AS build_version,
                  g.status AS gate_status,
                  (SELECT count(*) FROM incidents x WHERE x.installation_id=i.id AND x.status <> 'resolved') AS open_findings,
                  (SELECT count(*) FROM incidents x WHERE x.installation_id=i.id AND x.status <> 'resolved'
                     AND x.severity='critical') AS critical_findings
           FROM agent_installations i JOIN agents a ON a.id = i.agent_id
           JOIN organizations vo ON vo.id = a.vendor_org_id JOIN organizations co ON co.id = i.customer_org_id
           LEFT JOIN LATERAL (SELECT * FROM deployments WHERE installation_id=i.id AND status='deployed'
                              ORDER BY deployed_at DESC NULLS LAST LIMIT 1) d ON true
           LEFT JOIN builds b ON b.id = d.build_id
           LEFT JOIN LATERAL (SELECT status FROM deployments WHERE installation_id=i.id ORDER BY created_at DESC LIMIT 1) g ON true
           WHERE i.id = ANY($1::uuid[]) ORDER BY a.name, co.name""", ids)
    return [{**dict(r), "health": metrics_rollup.health(r["last_heartbeat_at"], 0, 0, r["critical_findings"])} for r in rows]


async def deployments(conn, installation_ids: list[UUID]) -> list[dict]:
    rows = await conn.fetch(
        """SELECT d.id, d.installation_id, d.status, d.deployed_at, d.created_at, b.id AS build_id, b.version,
                  b.source_digest, b.artifact_digest
           FROM deployments d JOIN builds b ON b.id = d.build_id
           WHERE d.installation_id = ANY($1::uuid[]) ORDER BY d.created_at DESC""", installation_ids)
    return [dict(r) for r in rows]


async def topology(conn, installation: dict, start) -> dict:
    comps = await conn.fetch(
        "SELECT id, component_key, kind, label, metadata, last_seen_at FROM agent_components WHERE installation_id=$1 ORDER BY kind, component_key",
        installation["id"])
    edges = await conn.fetch(
        "SELECT id, source_component_id, target_component_id, edge_kind FROM component_edges WHERE installation_id=$1",
        installation["id"])
    stats = await metrics_rollup.component_stats(conn, installation["id"], start)
    nodes = []
    for c in comps:
        s = stats.get(c["component_key"], {"calls": 0, "errors": 0, "p95_ms": None, "cost_usd": 0.0, "last_seen": None})
        last_seen = max(filter(None, [c["last_seen_at"], s["last_seen"]]), default=None)
        nodes.append({**dict(c), "metrics": s, "status": metrics_rollup.health(last_seen, s["calls"], s["errors"]),
                      "source": "observed" if s["calls"] else "registered (no telemetry in range)"})
    return {"installation_id": installation["id"], "nodes": nodes, "edges": [dict(e) for e in edges]}
