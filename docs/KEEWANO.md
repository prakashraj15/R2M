# Keewano integration (optional, advisory)

Keewano is a hosted event-analytics subscription. R2M's own trace store is the source of truth, and everything works with Keewano disabled. Keewano answers are **untrusted advisory data**. They can change which remediation OpsPilot *proposes*, never whether it is *allowed*: `DEPLOY-001` and the other policies still gate every action.

## Data flow

```
OpsPilot (SDK events) ──► /ingest/events ──► trace store
                                   │
                                   └─► outbox (only if KEEWANO_ENABLED and org enabled)
                                          │  keewano_adapter.map_event  (allowlisted, typed)
                                          ▼
                                  keewano_adapter.send_events ──► REST /event/ingress/v1/json/in
OpsPilot degraded turn ──► context["insights"].query ──► keewano_adapter.query ──► MCP (SQL tool)
```

## Typed events (frozen; types are append-only)

| ID | Name | Type | Source |
|----|------|------|--------|
| 2000 | DeploymentVersion | string | `step:DIAGNOSE` / `step:VERIFY` `deployment_version` (must match `v\d+.\d+`) |
| 2001 | IncidentCategory | string | `post_deploy_errors` / `capacity_pressure` / `unknown` |
| 2002 | RemediationProposed | string | `restart` / `rollback` / `scale` |
| 2003 | RemediationSucceeded | bool | `step:VERIFY` `recovered` (service healthy afterwards) |
| 2004 | PolicyOutcome | string | `allow` / `deny` / `approval_required` |
| 2005 | ToolFailureClass | string | `timeout` / `permission` / `refused` / `error` |
| 2006 | ExecutionLatencyMs | uint | `tool:*` span `duration_ms` (only if the outbox row carries it) |
| 2007 | BuildEvaluationPassed | bool | reserved |
| 2008 | RecommendationSource | string | `step:VERIFY` `recommendation_source`: keewano / deterministic / llm / user |

- **Entity:** one Keewano entity per R2M execution, `installId = uuid5(uuid5(URL, "https://r2m.demo/keewano"), "execution:<id>")`. No org, user or customer identifiers are ever sent.
- **Ordering:** the `step:VERIFY` mapping emits 2000 → 2001 → 2002 → 2003 together, so every incident stream ends with a complete outcome record.

## History query

`keewano_adapter.query()` opens an MCP Streamable-HTTP session with the `k-token: KEEWANO_PAT` header. It then **discovers** the SQL tool through `tools/list` instead of relying on a hard-coded name, and runs:

```sql
SELECT "RemediationProposed" AS remediation, "RemediationSucceeded" AS succeeded,
       count(DISTINCT user_id) AS incidents
FROM events
WHERE "IncidentCategory" = '<whitelisted category>' AND "RemediationSucceeded" IS NOT NULL
GROUP BY remediation, succeeded
```

- **Return value:** `{sample_count, recommendations: [{remediation, samples, successes}], category, tool, query, summary}`.
- **Unknown remediation names in the output are dropped.**
- **When the agent accepts the evidence** (`mock_agent/insights.py`): at least 20 incidents in total, the best candidate has at least 8 samples, and its recovery rate is at least 60%. Otherwise it labels the answer "insufficient history" and takes the deterministic safe step.

If the MCP tool needs a project argument, set `KEEWANO_PROJECT_ID`.

## Setup for the demo

1. Create a Keewano project. Put the **ingestion API key** in `KEEWANO_API_KEY` and a **personal access token** in `KEEWANO_PAT`, in `.env` only and never in git or chat.
2. Set `KEEWANO_ENABLED=true` and restart. Then enable Meridian's integration with `PUT /api/v1/integrations/keewano {organization_id, enabled: true}` as `security@meridian.demo`.
3. Backfill the synthetic history with `python scripts/seed_keewano.py --confirm` (298 synthetic entities over two weeks, per the Keewano guide). Wait about **5 minutes** for indexing.
4. Reset the degraded scenario and ask OpsPilot to "fix it":
   - **Keewano disabled:** the reply says *intelligence unavailable* and OpsPilot restarts the service.
   - **Keewano enabled:** the reply cites history showing rollback recovered 35 of 38 similar incidents. It proposes a rollback, and `DEPLOY-001` still requires approval.

## Verified live (2026-10-11)

- **MCP:** `tools/list` returns 13 tools. The adapter picks `run_sql_query(projectId, sqlQuery, maxRows)` by name, and takes `projectId` from `KEEWANO_PROJECT_ID` or from the SDK key's `projectId` claim.
- **Result format:** a summary line followed by CSV: `SQL result for project <id>: N row(s), M column(s).` then the header and rows.
- **Ingestion:** `POST /in` returns `202 {"received":n,"accepted":n}`. Event types 2000–2008 are registered.
- **Backfill:** 298 synthetic entities.
  - Post-deploy-error history: rollback recovered 52 of 57, restart 8 of 40.
  - Before/after by recommendation source: Keewano-informed recovered 65 of 72 (90%), deterministic 35 of 90 (39%).
- **Live run** (Operations Desk, degraded scenario): with Keewano on, the degraded turn proposes a Keewano-informed rollback (n=109). Without Keewano it proposes a restart labelled "intelligence unavailable".

Check your own setup with `python scripts/keewano_check.py --env-file .env --ingest --query`.
