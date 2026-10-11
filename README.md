# R2M — Responsibility to Monitoring

**AI agents act. Customers stay in control.**

R2M is an AI governance and runtime-control platform for agents that take real actions. A vendor ships an agent with its policies written as code. The customer's security team approves those exact policies. Every risky tool call must be authorized by R2M at runtime, and everything that happens is recorded as traces, cost and tamper-evident evidence.

> Hackathon prototype. Data is synthetic, sign-in is demo-only (not production authentication), and no real infrastructure is touched: the agent operates a simulated `payments-api`.

## The problem

AI agents are starting to restart services, scale clusters and roll back deployments. Observability tools only show what happened *after* the action. Enterprises buying agents from vendors need to **approve what an agent may do, enforce it before it acts, and get evidence afterwards**, independently of the vendor.

## What it does

| Capability | How |
|---|---|
| **Policies as code** | Vendor policies (`DEPLOY-001` rollback approval, `CAPACITY-001` scale limit, `DATA-001` log redaction) live in the agent's code and are registered by SHA-256 hash. The customer approves an exact hash. Changed code means a new hash and a new approval; a tampered version is refused. |
| **Runtime action gate** | Before any risky tool runs, the SDK asks R2M, which answers **ALLOW / DENY / REQUIRE_APPROVAL**. Risky actions need a human to approve the *exact* action (tool + arguments). |
| **Single-use grants** | An allowed action gets an HMAC-signed grant that expires in 60 s and is bound to the tenant, deployment, execution, tool and argument hash. The simulated infrastructure re-checks it, so a call that bypasses R2M is refused and opens a **critical incident**. |
| **Release gate** | A new agent build starts as *proposed* and can't act until its evals pass, its policies are approved and a release manager deploys it. The faulty build is blocked. |
| **Evidence and observability** | Traces (spans, decisions, grants), per-run model tokens and cost, incidents, and evidence records with SHA-256 integrity checks, plus an export. |
| **Keewano intelligence** | Agent runs are mirrored to Keewano as typed events. When something breaks, the agent asks Keewano over MCP which past fix actually worked, and uses that as its recommendation. Keewano is advisory only and never overrides the policy. |
| **Multi-tenant isolation** | Vendors and customers see only their own data, enforced in the API **and** by Postgres row-level security. Agents use per-customer SDK tokens. |

## Architecture

```
Browser ── Next.js UI (:3000) ── /api/* proxy ──► R2M Platform API (FastAPI, private :8000)
                                                       │            │
                                     Postgres on Aiven ◄┘            └► Keewano (events out, MCP query in)
                                     (TLS, row-level security)
OpsPilot agent (OpenAI) ── R2M SDK (per-customer token) ──► /actions/authorize ──► grant
        └── guarded tools ──► simulated payments-api (re-checks the grant)
```

One Docker image, one container, one public port (3000).

## Live demo walkthrough

Open **http://localhost:3000** and pick an identity in the top-right dropdown. Live agent replies take 20–40 s.

| Identity | Role |
|---|---|
| Meridian Financial · `customer_ops` | Runs the payments service, chats with OpsPilot |
| Meridian Financial · `customer_security` | Approves policies and risky actions |
| Atlas Applied AI · `vendor_developer` | Builds the agent, submits policies |
| Atlas Applied AI · `vendor_release_manager` | Evaluates and deploys builds |

**1. Live run, start to end**
1. As **customer_ops**, open **OpsPilot chat**, reset the **degraded** scenario, and send *"payments-api is throwing errors, please fix it"*.
2. OpsPilot observes and diagnoses, then asks Keewano. It proposes a **rollback to v2.0** (source: Keewano), which returns **REQUIRE_APPROVAL**.
3. As **customer_security**, open **Approvals → Operational actions** and approve the exact action.
4. As **customer_ops**, send *"approved, continue"*. You get **ALLOW → EXECUTE → VERIFY**, and payments-api is now v2.0 and healthy.
5. In **Agent workspace → Traces**, the run shows spans, the policy decision, the single-use grant (applied and consumed) and the model cost.

**2. Changing policy at runtime**
1. As **customer_security**, revoke **DEPLOY-001**. The next rollback request is immediately **DENIED** (`POLICY_NOT_APPROVED`).
2. As **vendor_developer**, re-submit it; as **customer_security**, approve it. Rollback is governed again.

**3. Controlling tools and cost**
- **Scale limit:** *"scale payments-api to 8 replicas"* needs approval under CAPACITY-001 (more than 4 replicas).
- **Cost:** model tokens and cost per run and per day, broken down by source.
- **Rate limits:** per user, per agent token and for Keewano queries.

**4. Keewano**
- **In R2M:** the agent's reply shows `source: keewano` and the number of supporting incidents, and the Keewano status shows events sent and the last query.
- **In the Keewano dashboard:** open the project to see the R2M event types (IDs 2000+) and the incoming events.

A one-page backup console is at `/live`. The API reference is at `/api/v1/docs`.

## Run it

**Docker (recommended):**
```bash
cp .env.example .env     # DATABASE_URL (Aiven), SESSION_SIGNING_KEY, SDK_TOKEN_SECRET; optional OPENAI_*, KEEWANO_*
# Aiven console → service → CA certificate → save as secrets/aiven-ca.pem
docker compose up -d --build                         # migrations run automatically on start
docker compose exec r2m python scripts/seed_demo.py  # demo orgs, identities, agent, simulated service
```
Then open http://localhost:3000.
- **Smoke test:** `python scripts/smoke_test.py --base http://127.0.0.1:3000`
- **Live end-to-end check:** `scripts/live_demo_check.py`. It changes demo state, so only run it against a demo database.

**Keewano (optional):** set `KEEWANO_ENABLED=true` and the keys, then:
```bash
python scripts/keewano_check.py --env-file .env --ingest      # register event types
python scripts/seed_keewano.py --env-file .env --confirm      # synthetic history (~5 min to index)
```

**Agent model:** with `OPENAI_API_KEY` set, OpsPilot runs live (`OPSPILOT_LLM_MODE=openai`). Without it, it falls back to a deterministic simulated model.

**SDK tokens** are per vendor+customer pair:
```bash
python scripts/sdk_token.py issue --vendor atlas-applied-ai --customer meridian-financial --label run-evals
```

**Local development (no Docker):**
```bash
uv venv -p 3.12 .venv && . .venv/bin/activate
uv pip install -e python/r2m_sdk -e "python[test]"
set -a; . ./.env; set +a
python scripts/init_db.py && python scripts/seed_demo.py
PYTHONPATH=python uvicorn r2m_platform.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
cd web && npm ci && npm run dev
```

## Tests

```bash
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/r2m_test pytest python/tests   # disposable DB: schema is wiped
pytest python/mock_agent/tests
(cd python/r2m_sdk && pytest)
(cd web && npm run typecheck && npm test)
```

The tests cover tenant isolation on every endpoint, cross-tenant access by direct ID, the approval and single-use grant flow, the release gate, out-of-order and duplicate event ingestion, row-level security, CSRF and rate limits, the Keewano outbox, and end-to-end runs with the real SDK. See [`docs/TEST_MATRIX.md`](docs/TEST_MATRIX.md).

## Repository layout

| Path | What |
|---|---|
| `python/r2m_platform/` | FastAPI platform: auth, tenancy, release gate, action gate, ingestion, metrics, evidence, Keewano outbox |
| `python/r2m_sdk/` | Installable agent SDK: tracing, `@tool` gate, code-owned policies, grant verification |
| `python/mock_agent/` | OpsPilot agent: workflow, live OpenAI mode, policies, tools, evals |
| `web/` | Next.js app: live UI (`/demo/agent`, `/approvals`, agent workspace), plus `/live` and `/session` |
| `db/migrations/` | Schema, invariant triggers, row-level security, one-round-trip SDK functions |
| `scripts/` | DB init and seed, evals, SDK tokens, Keewano setup, smoke and live checks |
| `docker/`, `Dockerfile`, `compose.yaml` | Single-container build and supervisor |

## Docs

| Doc | What |
|---|---|
| [`dev_docs/DEVELOPER_SPEC.md`](dev_docs/DEVELOPER_SPEC.md) | Product and build contract |
| [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) | Demo narrative |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) | Browser API and agent hook |
| [`docs/SDK_CONTRACT.md`](docs/SDK_CONTRACT.md) | SDK ↔ platform contract |
| [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) | Tenancy, approvals, grants, row-level security, known gaps |
| [`docs/KEEWANO.md`](docs/KEEWANO.md) | Keewano events and the MCP workflow |
| [`docs/TEST_MATRIX.md`](docs/TEST_MATRIX.md) | Acceptance criteria mapped to tests |
| [`docs/HANDOVER.md`](docs/HANDOVER.md), [`docs/FRONTEND_AGENT_HANDOVER.md`](docs/FRONTEND_AGENT_HANDOVER.md) | Team handover notes |

## Known limitations

- Demo authentication: identities are picked from a list, with no passwords.
- Synthetic data and a simulated `payments-api`; no real infrastructure, cloud or payment integration.
- Not a compliance attestation. The evidence checksums detect tampering but are not WORM storage.
- The "faulty build" chat scenario can error in live (OpenAI) mode. The release gate still blocks the faulty build.
