# R2M Security Model (prototype)

This is demonstrable engineering, not SOC 2, ISO 27001 or a legal audit attestation. Demo authentication is labeled non-production everywhere.

## Tenancy

- **Organizations** are `vendor`, `customer` or `internal`. A vendor sees an installation of its agent only while an **active** `vendor_customer_links` row exists. A customer sees only installations in its own org.
- **One scope query** (`SCOPE_SQL` in `r2m_platform/auth.py`) defines visibility. Every org-scoped endpoint resolves the caller's installations first and filters every query by them.
- **Hidden means 404.** Records outside scope return `404 not_found`, indistinguishable from missing records, so IDs can't be probed.
- **Per-object checks.** Direct object references (`/traces/{id}`, approvals, evidence export, demo installation) are scope-checked individually, not just by role.
- **Vendor-private fields are redacted for customers.** In trace payloads, customer viewers get attributes prefixed `prompt`, `completion`, `system_prompt` or `vendor_` redacted.
- **Tests.** `python/tests/test_platform.py` runs positive and negative scope tests for every agent-scoped endpoint, plus cross-tenant direct-object tests and SDK cross-tenant attribution.

## Authentication

| Caller | Mechanism | Notes |
|---|---|---|
| Browser | HMAC-SHA256 signed cookie `r2m_session` (HttpOnly, SameSite=Lax, Secure on https, 8 h) | Only seeded `is_demo` users. Session holds the user id only; roles are reloaded from the DB on every request |
| SDK / scripts | `Bearer SDK_INGEST_TOKEN`, constant-time compare | **Prototype limitation:** one global token. Production needs per-installation credentials over TLS. The server still checks that each event's deployment/agent/customer/vendor tuple is consistent |

## Authorization (roles → permissions)

| Role | Permissions |
|---|---|
| vendor_developer | register agents, submit policy revisions, Keewano query, demo |
| vendor_release_manager | evaluate releases, deploy, export evidence, demo |
| customer_security | decide approvals, export evidence, Keewano query/configure, demo |
| customer_ops | read, demo |

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
4. **Grants.** A grant is HMAC-SHA256 signed (`R2M_GRANT_SIGNING_KEY`, falling back to `SDK_INGEST_TOKEN`), and the SDK verifies it before running the tool. It is bound to org, deployment, execution, action, policy revisions, tool and argument hash, and expires in 60 s. Only `sha256(nonce)` is stored. A grant is used twice, each time atomically:
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
- **Keewano credentials** stay server-side. `integration_configs` stores enablement only. Keewano output is labeled untrusted advisory data and never feeds `/actions/authorize`.

## Known gaps (prototype)

- One shared SDK token instead of per-installation credentials. By default it is also the grant HMAC key; set `R2M_GRANT_SIGNING_KEY` to separate them.
- No Postgres row-level security. Scoping is at the application layer, plus triggers for the invariants above.
- No rate limiting or CSRF token. SameSite=Lax plus JSON-only bodies are the mitigation.
- Demo scenario reset is available to any in-scope demo role when `APP_ENV=demo`.
