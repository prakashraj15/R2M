# R2M Security Model (prototype)

This is demonstrable engineering, not SOC 2, ISO 27001 or a legal audit attestation. Demo authentication is labeled non-production everywhere.

## Tenancy

- **Organizations** are `vendor`, `customer` or `internal`. A vendor sees an installation of its agent only while an **active** `vendor_customer_links` row exists. A customer sees only installations in its own org.
- **One scope query** (`SCOPE_SQL` in `r2m_platform/auth.py`) defines visibility. Every org-scoped endpoint resolves the caller's installations first and filters every query by them.
- **Hidden means 404.** Records outside scope return `404 not_found`, indistinguishable from missing records, so IDs can't be probed.
- **Per-object checks.** Direct object references (`/traces/{id}`, approvals, evidence export, demo installation) are scope-checked individually, not just by role.
- **Vendor-private fields are redacted for customers.** In trace payloads, customer viewers get attributes prefixed `prompt`, `completion`, `system_prompt` or `vendor_` redacted.
- **Tests.** `python/tests/test_platform.py` runs positive and negative scope tests for every agent-scoped endpoint, plus cross-tenant direct-object tests and SDK cross-tenant attribution.

## Row-level security (defence in depth)

The application filters by scope, and Postgres enforces the same scope underneath (`db/migrations/0003_rls_and_sdk_credentials.sql`).

- **Restricted role.** API connections switch to `r2m_app`: not the table owner, no `BYPASSRLS`, and no UPDATE or DELETE on `audit_events`/`evidence_items`. Every tenant table has a policy limiting rows to the caller's installations (or orgs) for both reads and writes.
- **Scope is set per request in the same round trip.** Browser auth runs `r2m_apply_actor_scope`, SDK auth runs `r2m_apply_sdk_scope`, and the simulation runs at installation scope.
- **Unscoped means empty.** A pooled connection without a scope sees **zero** tenant rows, and releasing a connection clears its scope.
- **Bypass is narrow.** Only the outbox worker and SDK agent registration (a new installation, after the vendor/customer pair is validated) use the bypass flag. Migrations and seed scripts run as the owner.
- **Tested.** `test_row_level_security_blocks_unscoped_queries` covers it, and it was verified on Aiven: an unscoped query sees 0 rows, and an audit UPDATE is denied.
- **Limits.** RLS catches a query that forgets its tenant filter. It is **not** a defence against SQL injection, because the session can change its own settings. All SQL is parameterized.

## Authentication

| Caller | Mechanism | Notes |
|---|---|---|
| Browser | HMAC-SHA256 signed cookie `r2m_session` (HttpOnly, SameSite=Lax, Secure on https, 8 h) | Only seeded `is_demo` users. Session holds the user id only; roles are reloaded from the DB on every request |
| SDK / scripts | Per-customer bearer token `r2m_sdk_<credential id>_<HMAC-SHA256(SDK_TOKEN_SECRET, id)>`, issued with `scripts/sdk_token.py` | Each token is scoped to one vendor+customer pair, can be revoked, and nothing secret is stored in the DB. Every SDK endpoint enforces the pair: agent registration, policy registration, authorize, result, ingest and evals. Another customer's data gets `tenant_scope_invalid`, 404 or `scope_mismatch` |

## Authorization (roles → permissions)

| Role | Permissions |
|---|---|
| vendor_developer | submit policy revisions, update incident status, Keewano query, demo |
| vendor_release_manager | evaluate releases, deploy, export evidence, demo |
| customer_security | decide approvals, update incident status, export evidence, Keewano query/configure, demo |
| customer_ops | read, update incident status, demo |

Permissions are checked against the **owning** org of the record: the vendor org for releases and submissions, the customer org for approvals.

## Policy approval and runtime enforcement

1. **Policies are code.** They are registered by hash. A new hash is a new revision, which needs a new submission and approval. Approving a revision deactivates any other active revision of the same key for that installation, and a revoke deactivates it.
2. **Separation of duties.** The submitter cannot approve. This is enforced in the API **and** by the `approval_decisions` DB trigger, which also requires `customer_security` in the installation's customer org.
3. **`/actions/authorize` fails closed** (wire format in `docs/SDK_CONTRACT.md`). It checks, in order:
   - tenant scope: deployment, installation, agent, customer and environment must all line up
   - the deployment is `deployed`; SDK registration of new code only ever creates a `proposed` deployment
   - every policy that ever governed the tool is cited, with the active, exact approved hash
   - the strictest local verdict, which the server never relaxes

   Approval-required actions need a human approval of the **exact** action (tool, argument hash, execution). Each approval yields one grant.
4. **Grants.** A grant is HMAC-SHA256 signed with the calling agent's own per-customer token (or `R2M_GRANT_SIGNING_KEY` if set), so one customer's token can't mint grants that verify for another. The SDK verifies the grant before running the tool. It is bound to org, deployment, execution, action, policy revisions, tool and argument hash, and expires in 60 s. Only `sha256(nonce)` is stored. A grant is used twice, each time atomically:
   - **applied** (`applied_at`) once, at the simulated infrastructure
   - **consumed** (`consumed_at`) once, when the SDK reports the executed result; a replay gets 409 `grant_already_consumed`
5. **Independent check at the boundary.** `SimulationWorld.apply_action` refuses any mutation without a live grant for the same execution and tool, and opens a critical incident. "Policy enforcement coverage" is the share of observed mutations that carried a grant. It is **observed** coverage: code paths that never reach the simulation boundary are invisible, and the UI must say so.
6. **Tamper signal.** Re-registering a policy version with different code is refused (`hash_matches: false`), so the SDK fails closed. A high-severity incident is also opened.

## Data integrity

- **DB triggers** enforce the cross-table invariants that simple foreign keys cannot (`db/migrations/0002_grants_and_invariants.sql`):
  - a policy submission's revision agent must match the installation agent
  - an activation must mirror an approved submission and its hash
  - a deployment's build must be for the installation's agent
  - topology edges stay within one installation
  - a runtime approval's reviewer must be `customer_security` in the action's org
- **`audit_events` and `evidence_items` are append-only.** Triggers reject UPDATE and DELETE. This is an application-level guarantee, **not WORM storage**: a database superuser can still drop the triggers.
- **Evidence** stores canonical JSON plus its SHA-256. Reads recompute it (`integrity_ok`), and exports carry a manifest hash. This detects modification. It is not third-party timestamping.
- **Ingestion** is idempotent on `event_id` and tolerant of arrival order, with placeholders for not-yet-seen executions and spans. Attributes are sanitized: secret-looking keys are redacted, sizes are bounded.

## Secrets and transport

- **Secrets come only from the environment**, and the config check fails at startup if they are missing or shorter than 32 characters. They are never logged, never returned (the health check returns no driver detail) and never sent to the frontend.
- **Aiven is reached over TLS** with `verify-full`: CA verification plus hostname check. `DATABASE_SSL_MODE=disable` is refused unless the host is loopback, so there is no silent downgrade.
- **One public port.** FastAPI binds `127.0.0.1:8000`, and only Next.js `:3000` is published, bound to `127.0.0.1` on the host by compose.
- **Keewano credentials** stay server-side. `integration_configs` stores enablement only. Keewano output is labeled untrusted advisory data, is sanitized, and never feeds `/actions/authorize`.

## Request guards

- **CSRF.** Every cookie-authenticated write (POST, PUT, PATCH, DELETE), including login, must send `X-R2M-CSRF: 1`; otherwise it gets 403 `csrf_required`. A cross-site page can't add a custom header without a CORS preflight, and this API grants none. SDK calls with a bearer token are exempt. SameSite=Lax cookies are a second layer.
- **Rate limits** use fixed one-minute windows and return 429 `rate_limited` with `Retry-After`:

  | Scope | Limit per minute |
  |---|---|
  | Login, per IP | 20 |
  | Keewano query, per caller | 10 |
  | Demo agent message, per caller | 30 |
  | Browser, per session | 600 |
  | SDK, per token | 3000 |
  | Any caller, per IP | 3000 |

  `X-Forwarded-For` is trusted only from the in-container proxy. The counters live in process memory, which is fine for this single-process API; a multi-replica deployment would need shared counters.

## Known gaps (prototype)

- Demo authentication: any allowlisted identity can be selected without a password. It is labeled non-production.
- SDK tokens travel over loopback HTTP inside the container. A deployment with a separate agent host needs TLS for that hop.
- Rate-limit counters are per process and reset on restart.
- Demo scenario reset is available to any in-scope demo role when `APP_ENV=demo`.
