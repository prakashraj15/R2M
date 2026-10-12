# R2M — Responsibility to Monitoring

**AI agents act. Customers stay in control.**

R2M is an AI governance and runtime-control platform for agents that take real actions. A vendor ships an agent with its policies written as code. The customer's security team approves those exact policies. Every risky tool call must be authorized by R2M at runtime, and everything that happens is recorded as traces, cost and tamper-evident evidence.

> Data is synthetic and no real infrastructure is touched: the agent operates a simulated `payments-api`. Sign-in uses email and password (scrypt hashes, signed HttpOnly sessions).

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

Two separate apps in two containers. The agent is a vendor app that reaches R2M only over the network.

```
┌──────── opspilot (:3001) ─────────┐            ┌──────── r2m (:3000) ───────────────┐
│ Operations Desk UI (Next.js)      │            │ Control Plane UI (Next.js)         │
│ OpsPilot agent API (FastAPI)      │── SDK ────►│ R2M Platform API (FastAPI)         │
│  mock_agent + r2m SDK + OpenAI    │   HTTP     │  authorize · ingest · approvals    │
│  per-customer SDK token           │            │  /sim: simulated payments-api      │
└───────────────────────────────────┘            └────────┬──────────────┬────────────┘
                                                           ▼              ▼
                                           Postgres on Aiven     Keewano (events out,
                                           (TLS, row-level        MCP query in)
                                            security)
```

| Container | Image | Public URL | Contains |
|---|---|---|---|
| `r2m` | `r2m-control-plane` | http://localhost:3000 | Platform API (private :8000) + Control Plane UI |
| `opspilot` | `opspilot` | http://localhost:3001 | Agent API (private :8100) + Operations Desk UI. No database access, only an SDK token |

## Live demo walkthrough

There are two apps:
- **Control Plane** (http://localhost:3000): approvals, policies, release, traces, costs and evidence. Sign in with an account below; Sign out (top right) to switch roles.
- **Operations Desk** (http://localhost:3001): chat with OpsPilot. Sign in with the same R2M account; the agent service checks it against R2M and keeps its own session. Its "Review in R2M" and "Open R2M trace" links open the Control Plane.

Live agent replies take 20–40 s.

| Account | Org · role | Does |
|---|---|---|
| `ops@meridian.demo` | Meridian Financial · `customer_ops` | Runs the payments service, chats with OpsPilot |
| `security@meridian.demo` | Meridian Financial · `customer_security` | Approves policies and risky actions (read-only on the desk) |
| `dev@atlas.demo` | Atlas Applied AI · `vendor_developer` | Builds the agent, submits policies |
| `release@atlas.demo` | Atlas Applied AI · `vendor_release_manager` | Evaluates and deploys builds |

Passwords: `scripts/set_password.py` (see Run it). They are stored only as scrypt hashes.

**0. Release a new version (vendor → customer → release)**

A build is the agent's code plus its version. Releasing one is the whole release-gate story:
1. **Ship it.** Set `OPSPILOT_BUILD_VERSION=safe-1.2` in `.env` and run `docker compose up -d opspilot`.
2. **It registers as proposed.** Send any message on the desk. The status line under the chat says *Build safe-1.2 is proposed*, and every change OpsPilot attempts is denied (`DEPLOYMENT_NOT_ACTIVE`).
3. **CI evaluates it.** Run `docker compose exec opspilot python scripts/run_evals.py`. In the Control Plane under **Build evaluations**, `safe-1.2` now shows its suites and 24/24 passed. (`OPSPILOT_BUILD_VERSION=faulty-1.1` fails a mandatory test, and the gate blocks it.)
4. **Policies.** If the build ships a changed policy, the **vendor developer** opens **Policies** and clicks **Submit vX for … review**, then the **security reviewer** approves it under **Approvals**. Unchanged policies stay approved.
5. **Release.** As **release manager**, select the build and click **Evaluate release eligibility** (all four checks must pass), then **Deploy to production**. The desk status line now shows the live build.

**1. Live run, start to end**
1. In the **Operations Desk** (:3001), select the **degraded** scenario (this resets payments-api) and send *"payments-api is throwing errors, please fix it"*.
2. OpsPilot observes and diagnoses, then asks Keewano. It proposes a **rollback to v2.0** (source: Keewano), which returns **REQUIRE_APPROVAL**.
3. Click **Review in R2M**. In the **Control Plane** (:3000), as **Security reviewer**, approve the exact action under **Approvals**.
4. Back in the desk, send *"approved, continue"*. You get **ALLOW → EXECUTE → VERIFY**, and payments-api is now v2.0 and healthy.
5. Click **Open R2M trace**: spans, the policy decision, the single-use grant (applied and consumed) and the model cost.

**2. Changing policy at runtime**
1. As **customer_security**, revoke **DEPLOY-001**. The next rollback request is immediately **DENIED** (`POLICY_NOT_APPROVED`).
2. As **vendor_developer**, open **Policies** → DEPLOY-001 → **Submit for review**; as **customer_security**, approve it under **Approvals**. Rollback is governed again.

Keewano mirroring is switched on and off under **Orchestration** (security reviewer).

**3. Controlling tools and cost**
- **Scale limit:** *"scale payments-api to 8 replicas"* needs approval under CAPACITY-001 (more than 4 replicas).
- **Cost:** model tokens and cost per run and per day, broken down by source.
- **Rate limits:** per user, per agent token and for Keewano queries.

**4. Keewano**
- **In R2M:** the agent's reply shows `source: keewano` and the number of supporting incidents, and the Keewano status shows events sent and the last query.
- **In the Keewano dashboard:** open the project to see the R2M event types (IDs 2000+) and the incoming events.

API references: http://localhost:3000/api/v1/docs (platform) and http://localhost:3001/agent-api/docs (agent).

## Run it

**Docker (recommended):**
```bash
cp .env.example .env     # DATABASE_URL (Aiven), SESSION_SIGNING_KEY, SDK_TOKEN_SECRET; optional OPENAI_*, KEEWANO_*
# Aiven console → service → CA certificate → save as secrets/aiven-ca.pem
docker compose up -d r2m --build                     # platform first; migrations run on start
docker compose exec r2m python scripts/seed_demo.py  # orgs, accounts, agent, simulated service
# a random password per account, written once to a git-ignored file (or set your own: set_password.py EMAIL):
(umask 077; docker compose exec -T r2m python scripts/set_password.py --generate --all > secrets/accounts.txt)
# per-customer token for the OpsPilot container (written to .env as OPSPILOT_SDK_TOKEN):
docker compose exec r2m python scripts/sdk_token.py issue --vendor atlas-applied-ai --customer meridian-financial --label opspilot-agent
# also set OPSPILOT_SESSION_KEY in .env (32+ random characters; signs desk sign-in cookies)
docker compose up -d --build                         # starts opspilot once r2m is healthy
```
Then open http://localhost:3000 (Control Plane) and http://localhost:3001 (Operations Desk).
- **Smoke test:** `python scripts/smoke_test.py --base http://127.0.0.1:3000 --accounts secrets/accounts.txt`
- **End-to-end (agent ↔ platform over HTTP):** `pytest python/tests/test_opspilot_e2e.py` against a disposable database.

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
# agent service (separate process, talks to R2M over HTTP):
R2M_API_URL=http://127.0.0.1:3000 OPSPILOT_SDK_TOKEN=… R2M_VENDOR_ORG_ID=… R2M_CUSTOMER_ORG_ID=… \
  PYTHONPATH=python uvicorn opspilot_service.app:app --host 127.0.0.1 --port 8100
cd web && npm ci && npm run dev                                                  # Control Plane on :3000
cd web && NEXT_PUBLIC_R2M_APP=desk npx next dev --hostname 127.0.0.1 --port 3001  # Operations Desk
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
| `python/opspilot_service/` | OpsPilot agent API (separate container): HTTP world over R2M's `/sim` endpoints |
| `web/` | One Next.js codebase, built twice: Control Plane (`NEXT_PUBLIC_R2M_APP=control`) and Operations Desk (`=desk`). Framer Motion transitions |
| `db/migrations/` | Schema, invariant triggers, row-level security, one-round-trip SDK functions |
| `scripts/` | DB init and seed, evals, SDK tokens, Keewano setup, smoke and live checks |
| `Dockerfile`, `Dockerfile.opspilot`, `compose.yaml`, `docker/` | Two images and containers, plus their supervisors and health checks |

## Docs

| Doc | What |
|---|---|
| [`dev_docs/DEVELOPER_SPEC.md`](dev_docs/DEVELOPER_SPEC.md) | Product and build contract |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) | Browser API and agent hook |
| [`docs/SDK_CONTRACT.md`](docs/SDK_CONTRACT.md) | SDK ↔ platform contract |
| [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) | Tenancy, approvals, grants, row-level security, known gaps |
| [`docs/KEEWANO.md`](docs/KEEWANO.md) | Keewano events and the MCP workflow |
| [`docs/TEST_MATRIX.md`](docs/TEST_MATRIX.md) | Acceptance criteria mapped to tests |
| [`docs/HANDOVER.md`](docs/HANDOVER.md) | Team handover notes |

## Known limitations

- The agent keeps a pending action in process memory: if the OpsPilot container restarts between a rollback request and "approved, continue", the agent asks again (the old approval expires unused).
- Password sign-in only: no SSO/OIDC, MFA or self-service reset yet (`scripts/set_password.py` sets passwords). Setting a new password ends that user's Control Plane sessions; desk sessions run to their 8 h expiry.
- Synthetic data and a simulated `payments-api`; no real infrastructure, cloud or payment integration.
- Not a compliance attestation. The evidence checksums detect tampering but are not WORM storage.
