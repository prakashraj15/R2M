# R2M SDK ↔ Platform Contract (v1.0)

Owner: AI track. Consumers: backend (`r2m_platform`) implements these endpoints; the SDK
(`python/r2m_sdk`) is the only client. Reference fake implementation:
`python/r2m_sdk/src/r2m/testing.py` (`FakePlatform`) — backend behaviour must match it.

All paths are under `/api/v1`, called over loopback `http://127.0.0.1:8000`.

- Auth: `Authorization: Bearer <SDK_INGEST_TOKEN>` on every request.
- Each request sends a fresh `X-Request-ID` (UUID). The same ID is reused across that request's retries.
- Errors: `{code, message, request_id}`.
- The SDK retries on network errors and on 408/425/429/5xx. It does not retry other 4xx.

## 1. Agent registration — `POST /agents`

Request:
```json
{
  "slug": "opspilot", "name": "OpsPilot", "description": "…", "sdk_version": "0.1.0",
  "vendor_org_id": "uuid", "customer_org_id": "uuid", "environment": "demo|production|staging|development",
  "build": {"version": "safe-1.0", "source_digest": "sha256:…", "artifact_digest": "sha256:…"},
  "topology": {
    "components": [{"component_key": "llm", "kind": "model", "label": "OpsPilot Sim Model", "metadata": {}}],
    "edges": [{"source": "orchestrator", "target": "llm", "edge_kind": "calls"}]
  }
}
```
Response `200`: `{"agent_id", "installation_id", "deployment_id", "deployment_status"}`.
Registration is idempotent on `(vendor_org_id, slug)`, `(agent, customer, environment)` and
`(agent, artifact_digest)`. Components and edges are upserted into `agent_components` and
`component_edges` by `component_key`.

## 2. Policy registration — `POST /agents/{agentId}/policies/register`

Request:
```json
{"installation_id": "uuid", "deployment_id": "uuid",
 "policies": [{"id": "DEPLOY-001", "version": "1.0.0", "description": "…", "enforcement_point": "tool.pre_execute",
               "scope": "production", "owner": "…", "tools": ["rollback_deployment"],
               "artifact_hash": "sha256:…", "source_file": "deployment.py"}]}
```
Response:
```json
{"policies": [{"policy_id": "DEPLOY-001", "version": "1.0.0", "artifact_hash": "sha256:…",
               "revision_id": "uuid", "hash_matches": true,
               "status": "registered|pending|active|revoked"}]}
```
- Upsert `policy_revisions` on `(agent_id, policy_key, version, artifact_hash)`.
- Set `hash_matches=false` when this `(policy_key, version)` already exists with a different hash. Same version with different code is tampering.
- If the SDK doesn't get back an echoed matching hash, it **fails closed locally** for every tool bound to that policy.
- The artifact hash is SHA-256 over the canonical JSON of the policy metadata, then `\n`, then the source file with normalised line endings. The platform stores it but never recomputes it.

## 3. Runtime action gate — `POST /actions/authorize`

Request:
```json
{
  "action_id": null,
  "agent_id": "uuid", "deployment_id": "uuid", "installation_id": "uuid", "customer_org_id": "uuid",
  "environment": "production", "execution_id": "uuid", "trace_id": "uuid", "span_id": "uuid",
  "tool": "rollback_deployment", "risk": "high",
  "arguments_hash": "sha256:<hex of canonical JSON args>",
  "arguments": {"target_version": "2.0"},
  "local_decision": "ALLOW|DENY|REQUIRE_APPROVAL",
  "policies": [{"policy_id": "DEPLOY-001", "version": "1.0.0", "artifact_hash": "sha256:…",
                "decision": "REQUIRE_APPROVAL", "reason_code": "PRODUCTION_ROLLBACK_REQUIRES_APPROVAL"}]
}
```
- `arguments` is redacted and only for display. The binding uses `arguments_hash`.
- `action_id` is non-null only when the agent resumes a previously pending action.

Response:
```json
{
  "decision": "ALLOW|DENY|REQUIRE_APPROVAL",
  "reason_codes": ["…"], "decision_id": "uuid", "action_id": "uuid",
  "policy_revision_ids": ["uuid"],
  "approval_id": "uuid|null", "approval_status": "pending|approved|rejected|null",
  "grant": null
}
```

The server evaluates these checks in order:
1. Scope: the caller's token, `customer_org_id`, `deployment_id` and `agent_id` must be consistent. If not, return `DENY TENANT_SCOPE_INVALID`.
2. Resumed action (`action_id` set): the stored `tool_actions` row must match `tool`, `arguments_hash` and `execution_id` exactly. If not, return `DENY ACTION_BINDING_MISMATCH`.
3. Every listed policy hash must have an **active** `policy_activations` row for this installation. If not, return `DENY POLICY_NOT_APPROVED:<id>`. Stale, revoked or superseded hashes are denied.
4. `local_decision == DENY`: return `DENY` with the local reason codes. The server never relaxes a local DENY.
5. `local_decision == REQUIRE_APPROVAL`:
   - No `runtime_approvals` row yet: create one with status `pending`.
   - Approval `rejected`: return `DENY APPROVAL_REJECTED`.
   - Approval `pending`: return `REQUIRE_APPROVAL`.
   - Approval `approved` and not yet consumed: return `ALLOW` with `approval_status: "approved"`. The SDK only accepts an ALLOW over a local REQUIRE_APPROVAL when this field is present.
6. Otherwise, return `ALLOW` with a grant.

Always persist the `tool_actions` row (`requested_at`) and a `policy_decisions` row. Set `authorized_at` when the decision is ALLOW.

### Grant (included only with `ALLOW`)
```json
{"grant_id": "uuid", "action_id": "uuid", "decision_id": "uuid", "customer_org_id": "uuid",
 "deployment_id": "uuid", "policy_revision_ids": ["uuid"], "tool": "…", "arguments_hash": "sha256:…",
 "execution_id": "uuid", "expires_at": "ISO-8601 with offset, ≤ 60s ahead", "nonce": "random hex",
 "signature": "hex"}
```
- `signature = HMAC_SHA256(key, canonical_json({all fields above except signature}))`
- `canonical_json` is `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8.
- `key` is `R2M_GRANT_SIGNING_KEY` if set, otherwise `SDK_INGEST_TOKEN`.
- Store `sha256(nonce)` in `runtime_approvals.nonce_hash` or an equivalent unique column.
- The SDK verifies the signature, tool, arguments hash, execution, org, deployment, action, expiry, and that the nonce hasn't been used in this process.

## 4. Action outcome — `POST /actions/{actionId}/result`

After execution (`phase: "executed"`):
```json
{"grant_id": "uuid", "nonce": "hex", "phase": "executed", "outcome": "succeeded|failed",
 "executed_at": "ISO", "error_class": "TimeoutError|null", "result_metadata": {}}
```
- **Consume the grant atomically**: lock the row and check the nonce is unused and the grant hasn't expired.
- If the nonce was already consumed, return `409 grant_already_consumed`.
- Set `tool_actions.executed_at` and `outcome`. Mark the runtime approval `consumed`.

After the agent checks the effect (`phase: "verified"`):
```json
{"phase": "verified", "outcome": "verified|verification_failed", "verified_at": "ISO", "result_metadata": {}}
```
Set `verified_at`. "Authorized", "executed" and "verified" are different states and must stay separate.

## 5. Event ingestion — `POST /ingest/events`

Request: `{"events": [Event, …]}`, at most 100 per batch. Response: `{"accepted": n, "duplicates": n, "rejected": [{"event_id", "code"}]}`.

Event:
```json
{
  "event_id": "uuid", "schema_version": "1.0", "occurred_at": "ISO Z",
  "vendor_org_id": "uuid", "customer_org_id": "uuid", "agent_id": "uuid", "deployment_id": "uuid",
  "execution_id": "uuid|null", "trace_id": "uuid|null", "span_id": "uuid|null", "parent_span_id": "uuid|null",
  "span_kind": "orchestration|model|tool|memory|policy|infra|integration|null",
  "kind": "<see table>", "name": "string", "severity": "debug|info|warning|error|critical",
  "status": "string|null", "duration_ms": 12.3, "attributes": {}, "request_id": null
}
```
- The server sets `received_at`.
- Dedupe on `event_id` with `ON CONFLICT DO NOTHING`. Retries reuse the same IDs.
- Events can arrive in any order: a child span can arrive before its parent, and span events arrive when the span **ends**. Use `DEFERRABLE` FKs or insert-with-retry, and never drop events silently.

| `kind` | Meaning | Platform action |
|---|---|---|
| `execution.started` | run started or resumed (`attributes.resumed`) | upsert `executions` (id=`execution_id`, `trace_id`, `scenario`, `status=running`) |
| `execution.ended` | run finished (`status`: completed/failed) | set `executions.status`, `ended_at` |
| `span` | finished span; `occurred_at` = start, `duration_ms` | upsert `spans` (`id=span_id`, `parent_span_id`, `kind=span_kind`, `status`, `started_at`, `ended_at = start + duration`) |
| `state.transition` | agent workflow step (`from_state`, `to_state`) | `execution_events` |
| `model.call` / `tool.call` | tool outcome, `coverage` = observed / enforced | `execution_events` |
| `usage` | tokens, `amount_usd`, `cost_source`, `component_kind` | `usage_records` + `execution_events` |
| `policy.decision` | gate result incl. `decision_id`, `tool_action_id`, `authorization_outcome`, `reason_codes` | `execution_events` (authoritative row is written by `/actions/authorize`) |
| `heartbeat` | liveness; `execution_id` may be null | `agent_installations.last_heartbeat_at` |
| `insight` | Keewano/other advisory result (`insight_id`, `sample_count`, `proposed_action`) | `execution_events` |
| `error` | SDK-side failure (e.g. result report failed) | `execution_events`, possibly incident |

Status values: `ok`, `error`, `running`, `denied`, `pending_approval`.

- A `denied` span is an intended policy outcome, **not** a system error.
- Attributes are already redacted by the SDK. The platform must still validate size and allowlist keys before forwarding anything to Keewano.

## 6. SDK runtime guarantees (for docs, UI and security review)

- If the platform is unreachable at authorize time, the SDK returns `DENY AUTHORIZATION_UNAVAILABLE` and the tool doesn't run.
- If a policy throws, the result is `DENY POLICY_EVALUATION_ERROR`.
- Unguarded tools are traced with `coverage: "observed"`. R2M doesn't claim to prevent calls that bypass the SDK.
- Approving a policy revision doesn't approve future actions. Each REQUIRE_APPROVAL action needs its own runtime approval, and that approval is usable exactly once.

## 7. Backend behaviour stricter than `FakePlatform` (confirmed by the backend, 2026-10-11)

`FakePlatform` now mirrors all five rules; pass `auto_deploy=False` to get rule 1.

1. **New builds start as `proposed`.** `register_agent` with a never-seen `artifact_digest` returns `deployment_status: "proposed"`. Guarded tools get `DENY DEPLOYMENT_NOT_ACTIVE` until a release manager runs `releases/evaluate` and then `deploy`.
2. **Governing policies must be cited.** Every registered policy that lists the tool must appear in `policies`, or the response is `DENY GOVERNING_POLICY_NOT_CITED:<id>`. This stops a build that drops a decorator's policy binding from authorizing on its own. The server applies the strictest of `local_decision` and every per-policy `decision`.
3. **One grant per approval.** The runtime approval becomes `consumed` when its grant is *issued*. A replayed resume gets `DENY APPROVAL_CONSUMED`; an approval past its window gets `DENY APPROVAL_EXPIRED`.
4. **Tampered policies are refused.** The same `(id, version)` with a different hash returns `hash_matches: false`, `status: "rejected"` and `revision_id: null`, and opens a high-severity `policy_hash_mismatch:<id>` incident. The SDK then fails closed locally for that policy's tools.
5. **Only heartbeats may omit the execution.** Any other event with `execution_id: null` is rejected as `execution_required`. The SDK drops such events itself before sending, logs a warning and counts them in `R2MClient.dropped_outside_execution`.

## 8. Conventions the platform relies on

- **Topology:** spans and model calls carry `attributes.component = <component_key>` (`client.span(..., component=)`, `client.model_call(..., component=)`, `client.tool(..., component=)`). Usage events also carry `component`.
- **Workflow spans:** OpsPilot names its orchestrator spans `step:<STATE>`. The Keewano adapter reads only these attributes, and only after allowlisting them:
  - `step:DIAGNOSE`: `category`, `deployment_version`
  - `step:PROPOSE`: `tool`
  - `step:VERIFY`: `tool`, `recovered`, `category`, `deployment_version`
- **Insight events:** `kind: "insight"`, `name: "keewano.remediation_history"`. Attributes are `insight_id`, `status` (ok/failed/unavailable), `sample_count`, `supported`, `label`, `proposed_action`, `proposal_source` (keewano/deterministic) and `keewano_informed`.
