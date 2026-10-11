"""Agent registry, deployments and topology for scoped installations."""
from uuid import UUID

from ..errors import ApiError, conflict
from . import metrics_rollup
from .evidence_builder import audit


async def register_from_sdk(conn, body) -> dict:
    """SDK_CONTRACT §1. Idempotent upserts. A newly seen build gets a *proposed* deployment: only the release
    gate (evaluate + deploy) can make it deployed, so registering code never bypasses evaluation or approval."""
    linked = await conn.fetchval(
        """SELECT EXISTS(SELECT 1 FROM vendor_customer_links l JOIN organizations v ON v.id = l.vendor_org_id
           JOIN organizations c ON c.id = l.customer_org_id WHERE l.vendor_org_id=$1 AND l.customer_org_id=$2
           AND l.status='active' AND v.kind='vendor' AND c.kind='customer')""", body.vendor_org_id, body.customer_org_id)
    if not linked:
        raise ApiError(403, "tenant_scope_invalid", "vendor is not actively linked to this customer")
    b = body.build
    async with conn.transaction():
        agent_id = await conn.fetchval(
            """INSERT INTO agents(vendor_org_id, slug, name, description, sdk_version) VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (vendor_org_id, slug) DO UPDATE SET name=EXCLUDED.name,
               description=coalesce(EXCLUDED.description, agents.description), sdk_version=EXCLUDED.sdk_version
               RETURNING id""", body.vendor_org_id, body.slug, body.name, body.description, body.sdk_version)
        await conn.execute(
            """INSERT INTO agent_installations(agent_id, customer_org_id, environment, status) VALUES ($1,$2,$3,'active')
               ON CONFLICT (agent_id, customer_org_id, environment) DO NOTHING""", agent_id, body.customer_org_id, body.environment)
        inst_id = await conn.fetchval(
            "SELECT id FROM agent_installations WHERE agent_id=$1 AND customer_org_id=$2 AND environment=$3",
            agent_id, body.customer_org_id, body.environment)
        await conn.execute(
            """INSERT INTO builds(agent_id, version, source_digest, artifact_digest) VALUES ($1,$2,$3,$4)
               ON CONFLICT (agent_id, artifact_digest) DO NOTHING""", agent_id, b.version, b.source_digest, b.artifact_digest)
        build = await conn.fetchrow("SELECT id, version FROM builds WHERE agent_id=$1 AND artifact_digest=$2", agent_id, b.artifact_digest)
        if build["version"] != b.version:
            raise conflict("artifact digest already registered under another version")
        dep = await conn.fetchrow(
            """SELECT id, status FROM deployments WHERE installation_id=$1 AND build_id=$2
               ORDER BY (status='deployed') DESC, created_at DESC LIMIT 1""", inst_id, build["id"])
        if not dep:
            dep = await conn.fetchrow(
                "INSERT INTO deployments(installation_id, build_id, status) VALUES ($1,$2,'proposed') RETURNING id, status",
                inst_id, build["id"])
        for c in body.topology.components:
            await conn.execute(
                """INSERT INTO agent_components(installation_id, component_key, kind, label, metadata) VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT (installation_id, component_key) DO UPDATE SET kind=EXCLUDED.kind, label=EXCLUDED.label,
                   metadata=EXCLUDED.metadata""", inst_id, c.component_key, c.kind, c.label, c.metadata)
        if body.topology.edges:
            known = {r["component_key"]: r["id"] for r in await conn.fetch(
                "SELECT component_key, id FROM agent_components WHERE installation_id=$1", inst_id)}
            for e in body.topology.edges:
                if e.source not in known or e.target not in known or e.source == e.target:
                    raise ApiError(422, "validation_error", f"edge {e.source}->{e.target} references unknown components")
                await conn.execute(
                    """INSERT INTO component_edges(installation_id, source_component_id, target_component_id, edge_kind)
                       SELECT $1,$2,$3,$4 WHERE NOT EXISTS (SELECT 1 FROM component_edges WHERE installation_id=$1
                       AND source_component_id=$2 AND target_component_id=$3 AND edge_kind=$4)""",
                    inst_id, known[e.source], known[e.target], e.edge_kind)
        await audit(conn, None, body.vendor_org_id, "sdk.agent.register", "deployment", dep["id"], None,
                    {"slug": body.slug, "build_version": b.version, "artifact_digest": b.artifact_digest,
                     "environment": body.environment, "deployment_status": dep["status"]})
    return {"agent_id": agent_id, "installation_id": inst_id, "deployment_id": dep["id"], "deployment_status": dep["status"]}


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
