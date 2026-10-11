"""Dashboard numbers computed from raw facts on read. Missing telemetry is Unknown, never healthy.

ponytail: computed per request over bounded ranges; add workers/rollups.py materialization when demo data volume makes this slow.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

RANGES = {"1h": 1, "24h": 24, "7d": 168, "30d": 720}
STALE_AFTER = timedelta(minutes=15)


def since(range_key: str) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=RANGES[range_key])


def health(last_seen: datetime | None, calls: int, errors: int, critical_open: int = 0) -> str:
    if critical_open:
        return "critical"
    if last_seen is None or datetime.now(timezone.utc) - last_seen > STALE_AFTER:
        return "unknown"
    if calls and errors / calls >= 0.5:
        return "critical"
    if calls and errors / calls >= 0.1:
        return "degraded"
    return "healthy"


async def summary(conn, installation_ids: list[UUID], start: datetime) -> dict:
    ex = await conn.fetchrow(
        """SELECT count(*) FILTER (WHERE e.status='completed') AS ok,
                  count(*) FILTER (WHERE e.status IN ('completed','failed','cancelled')) AS finished,
                  count(*) AS total
           FROM executions e JOIN deployments d ON d.id = e.deployment_id
           WHERE d.installation_id = ANY($1::uuid[]) AND e.started_at >= $2""", installation_ids, start)
    findings = await conn.fetchval(
        """SELECT count(*) FROM incidents WHERE installation_id = ANY($1::uuid[])
           AND status <> 'resolved' AND severity IN ('high','critical')""", installation_ids)
    cov = await conn.fetchrow(
        """SELECT count(*) FILTER (WHERE sa.authorized) AS gated, count(*) AS observed
           FROM simulation_actions sa JOIN simulation_services s ON s.id = sa.service_id
           WHERE s.customer_org_id IN (SELECT customer_org_id FROM agent_installations WHERE id = ANY($1::uuid[]))
             AND sa.created_at >= $2""", installation_ids, start)
    costs = await conn.fetch(
        """SELECT u.cost_source, sum(u.amount_usd) AS usd, sum(u.input_tokens) AS input_tokens, sum(u.output_tokens) AS output_tokens
           FROM usage_records u JOIN executions e ON e.id = u.execution_id JOIN deployments d ON d.id = e.deployment_id
           WHERE d.installation_id = ANY($1::uuid[]) AND u.occurred_at >= $2 GROUP BY u.cost_source""", installation_ids, start)
    p95 = await conn.fetchval(
        """SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY s.duration_ms) FROM spans s
           JOIN executions e ON e.id = s.execution_id JOIN deployments d ON d.id = e.deployment_id
           WHERE d.installation_id = ANY($1::uuid[]) AND s.kind='tool' AND s.duration_ms IS NOT NULL AND s.started_at >= $2""",
        installation_ids, start)
    deployed = await conn.fetchval(
        "SELECT count(DISTINCT installation_id) FROM deployments WHERE installation_id = ANY($1::uuid[]) AND status='deployed'",
        installation_ids)
    return {
        "deployed_agents": deployed,
        "run_success": {"value": round(ex["ok"] / ex["finished"], 4) if ex["finished"] else None,
                        "completed": ex["ok"], "finished": ex["finished"], "total": ex["total"],
                        "status": None if ex["finished"] else "unknown"},
        "unresolved_high_severity_findings": findings,
        "policy_enforcement_coverage": {
            "value": round(cov["gated"] / cov["observed"], 4) if cov["observed"] else None,
            "numerator": cov["gated"], "denominator": cov["observed"],
            "explanation": "Observed coverage: simulated infrastructure mutations that carried a valid single-use grant, "
                           "divided by all mutations observed at the simulation boundary. Uninstrumented paths outside "
                           "the simulation are not observable; this is not proof of complete coverage."},
        "cost": {"total_usd": float(sum(c["usd"] or 0 for c in costs)),
                 "by_source": {c["cost_source"]: float(c["usd"] or 0) for c in costs},
                 "input_tokens": int(sum(c["input_tokens"] or 0 for c in costs)),
                 "output_tokens": int(sum(c["output_tokens"] or 0 for c in costs)),
                 "provenance_note": "Mocked model usage is labeled simulated; no real cloud or model pricing is claimed."},
        "p95_action_latency_ms": round(p95, 3) if p95 is not None else None,
    }


async def series(conn, installation_ids: list[UUID], start: datetime, bucket: str) -> list[dict]:
    rows = await conn.fetch(
        """SELECT date_trunc($3, u.occurred_at) AS bucket, u.cost_source, sum(u.amount_usd) AS usd
           FROM usage_records u JOIN executions e ON e.id = u.execution_id JOIN deployments d ON d.id = e.deployment_id
           WHERE d.installation_id = ANY($1::uuid[]) AND u.occurred_at >= $2 GROUP BY 1, 2 ORDER BY 1""",
        installation_ids, start, bucket)
    lat = await conn.fetch(
        """SELECT date_trunc($3, s.started_at) AS bucket, percentile_cont(0.95) WITHIN GROUP (ORDER BY s.duration_ms) AS p95,
                  count(*) AS calls, count(*) FILTER (WHERE s.status IN ('error','failed')) AS errors
           FROM spans s JOIN executions e ON e.id = s.execution_id JOIN deployments d ON d.id = e.deployment_id
           WHERE d.installation_id = ANY($1::uuid[]) AND s.started_at >= $2 AND s.duration_ms IS NOT NULL
           GROUP BY 1 ORDER BY 1""", installation_ids, start, bucket)
    return {"cost": [{"bucket": r["bucket"], "cost_source": r["cost_source"], "usd": float(r["usd"])} for r in rows],
            "latency": [{"bucket": r["bucket"], "p95_ms": r["p95"], "calls": r["calls"], "errors": r["errors"]} for r in lat]}


async def component_stats(conn, installation_id: UUID, start: datetime) -> dict:
    rows = await conn.fetch(
        """SELECT coalesce(s.attributes->>'component_key', s.attributes->>'component') AS key, count(*) AS calls,
                  count(*) FILTER (WHERE s.status IN ('error','failed')) AS errors,
                  percentile_cont(0.95) WITHIN GROUP (ORDER BY s.duration_ms) AS p95,
                  coalesce(sum(u.usd), 0) AS cost_usd, max(s.started_at) AS last_seen
           FROM spans s JOIN executions e ON e.id = s.execution_id JOIN deployments d ON d.id = e.deployment_id
           LEFT JOIN LATERAL (SELECT sum(amount_usd) AS usd FROM usage_records WHERE span_id = s.id) u ON true
           WHERE d.installation_id=$1 AND s.started_at >= $2 AND (s.attributes ?| array['component_key','component'])
           GROUP BY 1""", installation_id, start)
    return {r["key"]: {"calls": r["calls"], "errors": r["errors"], "p95_ms": r["p95"], "cost_usd": float(r["cost_usd"]),
                       "last_seen": r["last_seen"]} for r in rows}
