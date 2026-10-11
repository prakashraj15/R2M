# Test matrix

This maps the acceptance criteria in DEVELOPER_SPEC §12 to the checks that prove them.

| Status | Meaning |
|---|---|
| ✅ | automated and passing |
| 🧪 | manual or container check |
| ⏳ | blocked on another track |

## How to run

| Suite | Command | Needs |
|---|---|---|
| Platform | `TEST_DATABASE_URL=postgresql://…/r2m_test pytest python/tests` | a **disposable** Postgres (its schema is wiped) |
| SDK | `cd python/r2m_sdk && pytest` | nothing |
| Smoke (HTTP) | `python scripts/smoke_test.py --base http://127.0.0.1:3000` | a running container or API |

## Acceptance criteria (§12)

| Criterion | Check | Status |
|---|---|---|
| Exactly one app service and one container; only port 3000 exposed | `docker compose ps`, `docker ps`, `ss -lnt` inside the container | ⏳ needs `web/` |
| Both UIs routed by the frontend, API private behind the proxy | FastAPI binds `127.0.0.1:8000`; Next rewrite; smoke test via `:3000` | ⏳ needs `web/` |
| Aiven certificate verified; no credentials in responses, images or repo | Manual: `init_db.py` without the CA fails `SSLCertVerificationError`. `config.py` refuses TLS off for remote hosts. `/health/ready` returns no driver detail; `.env` and `secrets/` are git-ignored | 🧪 done 2026-10-11 |
| Every org-scoped endpoint has positive and negative RBAC tests | `test_agent_endpoints_are_tenant_scoped` (7 endpoints), `test_cross_tenant_direct_object_references` (trace by ID, evidence export, overview, SDK attribution), approvals 404/403 in `test_policy_approval_runtime_grant_and_single_use`, `test_incident_resolution_is_scoped_and_audited`, Keewano status scoping in `test_outbox_retries_then_sends_and_dead_letters` | ✅ |
| SDK is independently installable; nested spans; idempotent ingestion | SDK suite; `test_ingest_out_of_order_and_dedup` (child before parent, replayed batch = duplicates) | ✅ |
| Policy lives in agent code; a new version or hash needs re-approval; a stale approval can't authorize | `test_policy_approval_runtime_grant_and_single_use`: unapproved → `POLICY_NOT_APPROVED`, tampered hash → `hash_matches=false` + incident, dropped binding → `GOVERNING_POLICY_NOT_CITED` | ✅ |
| Rollback without a valid one-time grant is denied; execution linked to grant and decision | Same test: `REQUIRE_APPROVAL` → approve → ALLOW; replay → `APPROVAL_CONSUMED`; grant bound to execution; second apply refused; second result → `grant_already_consumed`. `test_full_governance_chain_with_real_sdk` does the same through the real SDK | ✅ |
| `safe` eval passes, `faulty` fails, a failing build can't be promoted | `test_release_gate_blocks_failing_build` (blocked + 409 `release_blocked`, digest mismatch, wrong role 403) | ✅ platform side; ⏳ real `run_evals.py` (AI) |
| Traces show model, tool, orchestration, decision, cost, latency; missing telemetry = Unknown | e2e trace assertions; metric `null` + `status: unknown` when no finished runs; topology `unknown` when stale | ✅ |
| Vendor and customer views differ by backend scope | Scope tests above; customer trace redaction (`redacted_for_customer`) | ✅ |
| Keewano on: typed events, real MCP query, recommendation changes. Off: clean fallback | `test_outbox_retries_then_sends_and_dead_letters` (fake adapter: enqueue, retry/backoff, send, dead-letter, query ok/failed/unavailable, output sanitized) | ✅ plumbing; ⏳ real adapter + live query (AI) |
| Demo reset safe, repeatable, synthetic only | `test_demo_reset_restores_state_and_closes_incidents` | ✅ |

## Negative and fault-injection cases

| Case | Where |
|---|---|
| No session, forged cookie, non-allowlisted identity, missing or wrong SDK token | `test_requires_session_and_sdk_token`, smoke test |
| SDK registers a vendor/customer pair that isn't linked → 403 | `test_cross_tenant_direct_object_references` |
| Authorize with another tenant's org → `TENANT_SCOPE_INVALID` | same |
| SDK registration never auto-deploys new code | `test_sdk_agent_registration_never_auto_deploys` |
| Local ALLOW hiding a per-policy REQUIRE_APPROVAL → server applies the strictest | `test_policy_approval_runtime_grant_and_single_use` |
| Resume with different arguments → `ACTION_BINDING_MISMATCH` | same |
| Forged nonce → `grant_invalid` | same |
| Unguarded mutation (faulty-build bypass) → refused + critical incident | same, and the e2e "bypass" step |
| Self-approval and cross-org approval blocked **in the DB** | `test_database_invariants` |
| Cross-installation topology edge; audit/evidence UPDATE or DELETE | `test_database_invariants` |
| Replayed resume must not rewrite an executed action's outcome | e2e `replay` step |
| Keewano down (send / query) → retry, then dead-letter; query `failed` | `test_outbox_retries_then_sends_and_dead_letters` |
