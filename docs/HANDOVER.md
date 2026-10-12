# Backend handover (2026-10-11)

> **Update:** R2M now ships as two apps in two containers: the Control Plane (`r2m`, :3000) and OpsPilot (`opspilot`, :3001). See the README's Architecture section.

The backend is done and tested: 15 platform tests, including an end-to-end test with the real `r2m` SDK, plus a smoke test against the shared Aiven database. The shapes are defined in two contracts:
- `docs/API_CONTRACT.md` for the browser and the agent hook
- `docs/SDK_CONTRACT.md` for the SDK, plus the backend notes on it in `API_CONTRACT.md`

The security behaviour is in `docs/SECURITY_MODEL.md`.

## Run the backend locally (everyone)

```bash
uv venv -p 3.12 .venv && . .venv/bin/activate
uv pip install -e python/r2m_sdk -e "python[test]"
cp .env.example .env        # ask Mohanaprasad for the shared Aiven values over a private channel, never in chat/git
                            # (SDK_TOKEN_SECRET is server-only; agents get per-customer tokens, see below)
# CA cert: Aiven console → service → CA certificate → save as secrets/aiven-ca.pem
set -a; . ./.env; set +a
python scripts/init_db.py && python scripts/seed_demo.py        # idempotent
PYTHONPATH=python uvicorn r2m_platform.main:app --host 127.0.0.1 --port 8000
```

- **API docs:** `http://127.0.0.1:8000/api/v1/docs`.
- **Smoke test:** `python scripts/smoke_test.py --base http://127.0.0.1:8000`.
- **Tests:** they need a *disposable* Postgres, because they wipe its schema:
  ```bash
  TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/r2m_test pytest python/tests
  ```
- **Latency:** the shared Aiven service is about 420 ms per round trip from here, so pages take 1–3 s. That's the network, not your code.

Accounts (passwords via `scripts/set_password.py`; stored as scrypt hashes):

| Email | Org | Role |
|---|---|---|
| `dev@atlas.demo` | Atlas Applied AI (vendor) | vendor_developer |
| `release@atlas.demo` | Atlas Applied AI | vendor_release_manager |
| `security@meridian.demo` | Meridian Financial (customer) | customer_security |
| `ops@meridian.demo` | Meridian Financial | customer_ops |
| `security@northwind.demo` | Northwind Health | unrelated tenant for isolation checks |

---

## For the UI developer

### Wiring (the Dockerfile depends on this)

- `web/next.config.ts`:
  - `output: "standalone"`
  - rewrites `/api/:path*` → `http://127.0.0.1:8000/api/:path*`
- `web/package-lock.json` must exist (the image runs `npm ci`), and so must a `web/public/` folder (the image copies it).
- **Browser calls are relative.** Call `/api/v1/...` and let the cookie ride along. **Every POST, PUT, PATCH or DELETE (login included) must send the header `X-R2M-CSRF: 1`**; otherwise it gets 403 `csrf_required`. Handle 429 `rate_limited` by honouring `Retry-After`. The session cookie is `HttpOnly`, so you can't read it. Call `GET /api/v1/me` instead.
- **Server-side fetches** go to `process.env.R2M_INTERNAL_API_URL` and must forward the incoming `cookie` header.
- No secrets in the frontend. The only allowed public variable is `NEXT_PUBLIC_APP_LABEL`.

### Sign-in

- **Sign in:** `POST /auth/session {email, password}` from the `/login` page. Sign out with `DELETE /auth/session`. To act as another role, sign out and sign in as that account.
- **Who am I:** `GET /me` returns orgs, roles and `permissions` per org. Use the permissions to show or hide buttons, but the backend enforces them regardless.

### Screens → endpoints

| Screen | Endpoints |
|---|---|
| `/` overview | `GET /organizations`, `GET /organizations/{orgId}/overview?range=24h` (6 metrics + agent registry + integrations) |
| `/agents/[id]` topology | `GET /agents/{id}/topology` (nodes with `status` and `metrics`, edges) |
| Policies | `GET /agents/{id}/policies` (revisions, submissions with `history`, `active`, `operational_decisions`, `coverage_caveat`) and `POST /agents/{id}/policies/{revisionId}/submit {installation_id}` (vendor dev) |
| Approvals | `GET /approvals` (`kind: policy \| runtime_action`, `can_decide`) and `POST /approvals/{id}/decision {decision, reason}` |
| Evaluations | `GET /agents/{id}/evaluations` (runs → cases with expected vs actual, `mandatory_failure`) |
| Release (new) | `POST /agents/{id}/releases/evaluate {installation_id, build_version, artifact_digest}` → checks, then `POST /agents/{id}/deployments/{depId}/deploy` (release manager). `GET /agents/{id}/deployments` |
| Traces | `GET /agents/{id}/traces?cursor=` and `GET /traces/{traceId}` (spans with `depth`, `started_at` and `duration_ms` for the waterfall; events, actions, decisions, grants, approvals, usage) |
| Costs / metrics | `GET /agents/{id}/metrics?range=` (`summary` plus `series.cost[]` / `series.latency[]`) |
| Security | `GET /agents/{id}/incidents` and `PATCH /incidents/{id} {status, note}` (resolve or investigate; feeds "unresolved findings") |
| Evidence | `GET /agents/{id}/evidence` (`integrity_ok` per item) and `GET /agents/{id}/evidence/export` (customer security / release manager) |
| Integrations | `GET/PUT /integrations/keewano`, `POST /integrations/keewano/query` |
| Operations Desk (separate app, :3001) | Chat goes to the OpsPilot agent API: `POST /agent-api/message`, `GET /agent-api/state`, `POST /agent-api/scenarios/{id}/reset` (see `API_CONTRACT.md`) |

### Rules the spec cares about

- **`null` means Unknown.** Never show it as healthy or as 0%. Run success, coverage, p95 and node status can all be `null` or `unknown`.
- **Label cost provenance.** Show the `cost.by_source` keys, and badge mocked model cost as **simulated**.
- **Show the coverage explanation.** Display `policy_enforcement_coverage.explanation` next to the number; it's observed coverage, not proof.
- **Out-of-scope is 404.** Treat it as "not found", never as "forbidden".
- **Customer views are redacted.** When `redacted_for_customer` is true, trace attributes show `[vendor-private]`.
- **A new agent build can't act until it's released.** It shows as `proposed`. The demo needs a release step: run evals, approve the policy, evaluate, deploy. See the walkthrough in the README.
- **The agent is a separate container** (`opspilot`, :3001). It reaches R2M only over HTTP with a per-customer SDK token; the platform no longer runs it in-process.

---

## For the AI developer

### Your SDK is wired in

The backend implements `SDK_CONTRACT.md`, and `GrantVerifier` accepts server-signed grants. `python/tests/test_sdk_e2e.py` runs your SDK against a live server through the whole chain.

It is **deliberately stricter than `FakePlatform`** in these places:
1. **New builds start as `proposed`.** `register_agent` with a never-seen build returns `deployment_status: "proposed"`, and guarded tools get `DENY DEPLOYMENT_NOT_ACTIVE` until a release manager evaluates and deploys it.
2. **Governing policies must be cited.** Every registered policy that lists the tool has to be cited, or you get `GOVERNING_POLICY_NOT_CITED:<id>`. The server applies the strictest of `local_decision` and each per-policy decision.
3. **One grant per approval.** A replayed resume gets `APPROVAL_CONSUMED`; expired approvals get `APPROVAL_EXPIRED`.
4. **Tampered policies are refused.** Same `(id, version)` with a different hash returns `hash_matches: false`, `status: "rejected"` and `revision_id: null`, and opens a high-severity incident.
5. **Only heartbeats may omit the execution.** Any other event without an `execution_id` is rejected as `execution_required`.
6. **SDK tokens are per customer.** Each one is scoped to a vendor+customer pair, so there's no shared `SDK_INGEST_TOKEN` on the server any more; agents pass their own token. A token used for another customer's data gets `tenant_scope_invalid`, 404 or `scope_mismatch`.

   Grants are signed with the calling token, which matches the SDK's default `GrantVerifier(grant_key or token)`, so `R2M_GRANT_SIGNING_KEY` can stay unset.

Please note these six in `SDK_CONTRACT.md`.

### `mock_agent` contract

`python/mock_agent/agent.py` is installed by `python/pyproject.toml`, so the Docker image picks it up.

```python
def handle_message(message: str, scenario: str, context: dict) -> dict: ...   # sync or async both fine
```

- **Threading:** it runs in a worker thread, so a blocking `httpx` call to `context["api_url"]` is safe.
- **Building the client:** use `R2MClient(token=context["sdk_token"], agent_slug="opspilot", vendor_org_id=context["vendor_org_id"], customer_org_id=context["customer_org_id"], environment=context["environment"], base_url=context["api_url"])`. The environment is `"production"`. Call `client.close()` (or `flush()`) before returning.
- **Mutations go through the world, inside the guarded tool:**
  ```python
  @client.tool("rollback_deployment", risk="high", policies=[DEPLOY_001])
  def rollback_deployment(target_version: str):
      return context["world"].apply_action("rollback_deployment", {...state changes...},
                                           r2m.current_execution().execution_id)
  ```
  The world applies the change only if `/actions/authorize` issued a live grant for that execution and tool. An unguarded call is refused, logged as `authorized=false` and opens a critical incident. That is your scenario-4 "faulty build" signal.
- **Reads:** `world.get_service()` and `world.deployment_history()`.
- **Resuming after approval:** the reviewer approves in the R2M UI, then the next chat message must resume **the same execution and action**. Use `client.execution(execution_id=..., resume=True)` and `with r2m.resume_action(action_id):`.

  `handle_message` holds no state between calls, so keep `{action_id, execution_id}` from the last `ApprovalRequired`, for example in a module-level dict keyed by `customer_org_id`.
- **Return value:** something JSON-able, e.g. `{reply, execution_id, trace_id, decision, action_id, approval_id, state}`. The UI links the trace using `trace_id`.
- **Reference implementation:** `python/tests/opspilot_stub.py` is a minimal working version of all of the above.
- **Topology:** register components with `component_key`s and put `component=<key>` on spans, including model spans. That makes topology nodes light up with calls, errors, p95 and cost.

### `scripts/run_evals.py`

- Post each suite to `POST /api/v1/agents/{agentId}/evaluations` with a per-customer SDK token. Issue it once with `python scripts/sdk_token.py issue --vendor atlas-applied-ai --customer meridian-financial --label run-evals` and pass it in via the environment. The token must belong to the agent's vendor. The body shape is in `API_CONTRACT.md`.
- Use **the same `artifact_digest`** that the agent passes to `register_agent`; the release gate compares them.
- The faulty build must fail a `mandatory` case, so its release is `blocked`.
- The OpsPilot agent id is the deterministic `uuid5(uuid5(NAMESPACE_URL, "https://r2m.demo/seed"), "agent:opspilot")`, or take `agent_id` from the `register_agent` response.

### Keewano

- Implement `python/r2m_platform/services/keewano_adapter.py`:
  - `map_event(event: dict) -> dict | None`: pure, sanitized, `None` to skip
  - `async send_events(payloads: list[dict])`: raise on failure
  - `async query(question, context) -> dict`: include `sample_count`
- The outbox, retry, dead-lettering, timeout and audit are already built. They activate when `KEEWANO_ENABLED=true` and the customer org has it enabled via `PUT /integrations/keewano`.
- Emit the agent's advisory result as an `insight` event (`insight_id`, `sample_count`, `proposed_action`). When Keewano is unavailable, the query endpoint returns `status: "unavailable"`; show "intelligence unavailable" and never claim a Keewano-informed recommendation.
