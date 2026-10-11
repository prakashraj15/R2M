# R2M API Contract (v1)

Base path `/api/v1`. The browser reaches it through the Next.js `/api/*` proxy on port 3000; FastAPI itself listens only on `127.0.0.1:8000`. Live schema: `/api/v1/docs` (OpenAPI at `/api/v1/openapi.json`).

## Conventions

- **JSON, UTC ISO 8601 times, UUID ids.**
- **`X-Request-ID`**: if you send `[A-Za-z0-9._-]{1,64}`, it is echoed back. Otherwise the server generates one. It also appears in every error body.
- **Errors**: `{"code": "...", "message": "...", "request_id": "..."}`. Validation errors add `fields: [{loc, msg}]` and never echo the input.
- **Out-of-scope is 404**: a record that exists but belongs to another tenant returns the same `404 not_found` as a missing one.
- **Pagination**: `GET /agents/{id}/traces` takes `limit` (1–200) and `cursor`, and returns `next_cursor`. Other lists take a bounded `limit`.
- **Time ranges**: `range=1h|24h|7d|30d` (default `24h`).
- **Installation selector**: agent-scoped GETs take an optional `installation_id`. Without it, they cover every installation the caller can see.

| Code | HTTP | Meaning |
|---|---|---|
| `unauthenticated` | 401 | no/invalid demo session cookie, or bad SDK bearer token |
| `tenant_scope_invalid` | 403 | SDK registration for a vendor/customer pair that isn't actively linked |
| `forbidden` | 403 | in scope, but the role lacks the permission |
| `not_found` | 404 | missing **or outside your tenant scope** |
| `conflict` / `invariant_violation` | 409 | state conflict / a DB trigger rejected the write |
| `release_blocked` | 409 | deploy attempted on a non-eligible deployment |
| `not_authorized` | 409 | result reported for an action that was never authorized |
| `no_active_deployment` | 409 | demo agent has no deployed build |
| `validation_error` | 422 | body/query failed validation |
| `agent_unavailable` / `agent_error` | 503 / 502 | `mock_agent` not installed / it raised |

## Authentication

- **Browser:** `POST /demo/session {"email"}` sets an HMAC-signed `r2m_session` cookie (`HttpOnly`, `SameSite=Lax`, 8 h). Only seeded `is_demo` users are accepted. **This is demo auth, not production auth.**
- **SDK / scripts:** `Authorization: Bearer $SDK_INGEST_TOKEN`. This is accepted only on `POST /agents`, `/ingest/events`, `/actions/*`, `/agents/{id}/policies/register` and `POST /agents/{id}/evaluations`.

Seeded identities (`scripts/seed_demo.py`):

| Email | Org | Role |
|---|---|---|
| `dev@atlas.demo` | Atlas Applied AI (vendor) | vendor_developer |
| `release@atlas.demo` | Atlas Applied AI | vendor_release_manager |
| `security@meridian.demo` | Meridian Financial (customer) | customer_security |
| `ops@meridian.demo` | Meridian Financial | customer_ops |
| `security@northwind.demo` | Northwind Health (unrelated customer) | customer_security |

Permissions by role: `GET /me` returns them per org. The source of truth is `PERMISSIONS` in `r2m_platform/auth.py`.

## Browser endpoints (cookie)

| Method | Path | Notes |
|---|---|---|
| GET | `/health/live` | unauthenticated, no DB |
| GET | `/health/ready` | `{"status":"ready"}` or 503; no driver detail |
| GET | `/demo/identities` | allowlisted identities for the login picker |
| POST/DELETE | `/demo/session` | sign in as `{email}` / sign out |
| GET | `/me` | user, orgs, roles, permissions, `demo_auth: true` |
| GET | `/organizations` | the caller's orgs only |
| GET | `/organizations/{orgId}/overview?range=` | `metrics` (6 KPIs below), `agents` registry rows, `integrations` |
| GET | `/agents` | list scoped installations (`POST /agents` is SDK registration, see below) |
| GET | `/agents/{id}/topology?installation_id&range` | `nodes` (component + `metrics{calls,errors,p95_ms,cost_usd}` + `status` healthy/degraded/critical/unknown + `source`) and `edges` |
| GET | `/agents/{id}/deployments` | deployments with build version and digests |
| POST | `/agents/{id}/releases/evaluate` | `{installation_id, build_version, artifact_digest}` → `{deployment_id, status: eligible\|blocked, eligible, checks{build_evals_passed, required_policies_approved, artifact_hash_matches, tenant_access_valid}, details}` (vendor_release_manager) |
| POST | `/agents/{id}/deployments/{depId}/deploy` | re-checks the gate. 409 `release_blocked` unless eligible |
| GET | `/agents/{id}/evaluations` | `runs[]` with build, suite, status, `mandatory_failure`, `cases[]` (expected/actual/trace_id/evidence_hash) |
| GET | `/agents/{id}/policies` | revisions with hash, owner, `submissions[]` (status, `history[]`, `active`), `operational_decisions{allow,deny,require_approval}`, `coverage_caveat` |
| POST | `/agents/{id}/policies/{revisionId}/submit` | `{installation_id, note?}` (vendor_developer) → `{submission_id, status: pending}` |
| GET | `/approvals?status=` | mixed list. `kind: policy` (submission) or `runtime_action` (exact tool+arguments). Includes `can_decide` |
| POST | `/approvals/{id}/decision` | `{decision: approve\|reject\|revoke, reason?}` (customer_security, never the submitter). Runtime approvals take approve/reject only |
| GET | `/agents/{id}/traces?limit&cursor` | runs: execution/trace ids, status, scenario, build, span/decision counts, cost |
| GET | `/traces/{traceId}` | `execution`, `spans[]` (with `depth` for the waterfall), `events[]`, `actions[]`, `decisions[]`, `grants[]` (never the token), `approvals[]`, `usage[]`, `insights[]`, `redacted_for_customer` |
| GET | `/agents/{id}/metrics?range` | `summary` (same shape as overview metrics), `series{cost[], latency[]}` by hour/day |
| GET | `/agents/{id}/incidents` | open/resolved findings with `trace_id` |
| PATCH | `/incidents/{id}` | `{status: open\|investigating\|resolved, note?}` (customer_security, customer_ops, vendor_developer); evidence + audit recorded |
| GET | `/agents/{id}/evidence` | items with `sha256` and recomputed `integrity_ok`, plus `caveat` |
| GET | `/agents/{id}/evidence/export` | bundle with `manifest_sha256` (customer_security / vendor_release_manager); audited |
| GET/PUT | `/integrations/keewano` | status (`platform_enabled`, `adapter_installed`, per-org enabled/backlog/dead) / `{organization_id, enabled}` (customer_security) |
| POST | `/integrations/keewano/query` | `{installation_id, question}` → `{status: ok\|failed\|unavailable, insight_id, result, trust: "untrusted advisory data"}` |
| POST | `/demo/agent/message?installation_id` | `{message, scenario: healthy\|degraded\|approval\|faulty}` → the agent's dict, sanitized |
| POST | `/demo/agent/scenarios/{id}/reset` | resets synthetic `payments-api` state and expires open runtime approvals (only when `APP_ENV=demo`) |
| GET | `/demo/agent/state` | `services[]`, `scenarios`, `recent_actions[]` (with `authorized`), `approvals[]`, `last_execution` |

**Overview/agent metric shape:** `deployed_agents`, `run_success{value,completed,finished,total,status}`, `unresolved_high_severity_findings`, `policy_enforcement_coverage{value,numerator,denominator,explanation}`, `cost{total_usd,by_source{observed,estimated,allocated,simulated},input_tokens,output_tokens,provenance_note}`, `p95_action_latency_ms`.

`null` means **Unknown** (no telemetry in range). The UI must never show `null` as healthy or as 0%.

## SDK endpoints (bearer token)

`docs/SDK_CONTRACT.md` (owned by AI) is authoritative for request and response shapes. It covers:
- `POST /agents`
- `POST /agents/{id}/policies/register`
- `POST /actions/authorize`
- `POST /actions/{id}/result`
- `POST /ingest/events`

The backend implements that contract. `python/tests/test_sdk_e2e.py` drives it with the real `r2m` SDK against a live server, and `GrantVerifier` accepts the server-signed grants. The table below lists where the backend is **deliberately stricter** than `FakePlatform`:

| Area | Backend behaviour |
|---|---|
| `POST /agents` | A build seen for the first time gets a **`proposed`** deployment, never `deployed`. Its guarded actions return `DENY DEPLOYMENT_NOT_ACTIVE` until a release manager runs `releases/evaluate` and then `deploy`. Vendor and customer must be actively linked, or it returns 403 `tenant_scope_invalid` |
| Policy register | If the same `(id, version)` arrives with a different hash, it is not stored. The response has `hash_matches: false`, `status: "rejected"`, `revision_id: null`, and a high-severity `policy_hash_mismatch:<id>` incident is opened |
| Authorize checks | After the tenant scope check (`TENANT_SCOPE_INVALID`), the deployment must be `deployed` (`DEPLOYMENT_NOT_ACTIVE`). Every policy ever registered that lists the tool must be cited (`GOVERNING_POLICY_NOT_CITED:<id>`). The effective local verdict is the strictest of `local_decision` and every per-policy `decision` |
| Approvals | One grant per approval: the approval becomes `consumed` when its grant is issued. A replayed resume gets `DENY APPROVAL_CONSUMED`; an expired one gets `APPROVAL_EXPIRED` |
| Result `executed` | Other error codes besides `grant_already_consumed`: `grant_invalid` (wrong grant or nonce), `grant_expired`, `not_authorized`. A later decision never overwrites an action that already executed |
| Ingest | Only `heartbeat` may have `execution_id: null`; other events without one are rejected as `execution_required`. A span `attributes.component` (or `component_key`) that matches a topology `component_key` feeds node metrics and freshness |

Grant key: `R2M_GRANT_SIGNING_KEY`, falling back to `SDK_INGEST_TOKEN`. TTL is 60 s.

### `POST /agents/{agentId}/evaluations` (used by `scripts/run_evals.py`, not part of the SDK contract)

```json
{"build": {"version": "safe-1.0", "source_digest": "sha256:...", "artifact_digest": "sha256:..."},
 "suite_key": "opspilot.policy_regression", "suite_description": "...", "mandatory": true,
 "started_at": "...", "finished_at": "...",
 "cases": [{"case_key": "rollback_requires_grant", "mandatory": true, "status": "passed|failed|error|skipped",
            "expected": {}, "actual": {}, "trace_id": "uuid?"}]}
```

The response is `{run_id, build_id, status, summary}`. A run fails if any mandatory case fails or errors. The gate then requires the latest run of every mandatory suite this agent has ever run to be `passed` for that build. Use the **same** `artifact_digest` that the agent passes to `register_agent`; that ties evals, release and runtime to one build.

## Agent hook (backend ⇄ AI)

`POST /demo/agent/message` calls `mock_agent.agent.handle_message(message: str, scenario: str, context: dict) -> dict`.

- **Threading.** It runs in a worker thread. A sync function is called directly; a coroutine function is run with `asyncio.run` in that thread. Either way, the SDK's loopback calls to `context["api_url"]` cannot deadlock the server.
- **Context.** `context` holds `world`, `agent_id`, `installation_id`, `deployment_id`, `build_version` (the currently deployed build), `customer_org_id`, `vendor_org_id`, `environment` (`production`), `api_url`, `request_id`, `actor{user_id,email,roles}`. Build `R2MClient` from these, plus `SDK_INGEST_TOKEN` from the environment. The client's own `register_agent` returns the deployment id for *its* build.
- **Return value.** Return something JSON-able, e.g. `{reply, execution_id, trace_id, decision, action_id, approval_id, state}`. Secret-looking keys are redacted before the browser sees them.

`context["world"]` (`SimulationWorld`, synchronous):

| Method | Returns |
|---|---|
| `get_service(service_key="payments-api")` | `deployment_version, previous_version, replicas, cpu_pct, memory_pct, error_rate_pct, p95_latency_ms, health_status` |
| `deployment_history(service_key=...)` | last 20 simulated actions |
| `apply_action(tool, changes, execution_id)` | `{applied: True, action_id, before, after}`, or `{applied: False, reason, incident_id}` |

Call `apply_action` **inside the guarded tool body**, passing `r2m.current_execution().execution_id`. It atomically claims the live grant that `/actions/authorize` issued for that execution and tool, and a grant can be applied once.

With no grant (an unguarded call, as in the faulty build), nothing changes. An `authorized=false` simulation action is recorded and a **critical** `unauthorized_action_attempt` incident is opened.

`changes` may only touch the state fields above. See `python/tests/opspilot_stub.py` for a minimal working agent.

## Keewano adapter hook (backend ⇄ AI)

`r2m_platform/services/keewano_adapter.py` (AI-owned) must expose three functions. If the module is missing, the platform behaves as "intelligence unavailable".

| Function | Contract |
|---|---|
| `map_event(event: dict) -> dict \| None` | Sanitized Keewano payload, or `None` to skip. Runs inside the ingest transaction, so keep it pure |
| `async send_events(payloads: list[dict]) -> None` | Raise on failure. The outbox retries with backoff and dead-letters after 8 attempts |
| `async query(question: str, context: dict) -> dict` | Include `sample_count`, and optionally `request_id`. 20 s timeout. Stored in `insight_queries` |

The outbox worker runs only when `KEEWANO_ENABLED=true` and the customer org has the integration enabled (`PUT /integrations/keewano`).
