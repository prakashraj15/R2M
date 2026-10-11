# R2M — Responsibility to Monitoring

R2M is an AI governance, runtime-control, evidence, evaluation, cost and observability platform. This repo is a hackathon prototype: one container serves the R2M dashboard and the OpsPilot demo agent (`/demo/agent`). All data is synthetic, authentication is **demo-only**, and no real infrastructure is touched.

## One-command run (Docker)

```bash
cp .env.example .env            # fill DATABASE_URL (Aiven), SESSION_SIGNING_KEY, SDK_INGEST_TOKEN
# Aiven console → service → CA certificate → save as secrets/aiven-ca.pem
docker compose up -d --build && docker compose exec r2m sh -c "python scripts/init_db.py && python scripts/seed_demo.py"
```

Open http://localhost:3000. Pick a demo identity: `dev@atlas.demo`, `release@atlas.demo`, `security@meridian.demo` or `ops@meridian.demo`.

- **Smoke test:** `docker compose exec r2m python scripts/smoke_test.py`.
- **Teardown:** `docker compose down`. The hosted Aiven data is untouched.

## Local development (no Docker)

```bash
uv venv -p 3.12 .venv && . .venv/bin/activate
uv pip install -e python/r2m_sdk -e "python[test]"
set -a; . ./.env; set +a
python scripts/init_db.py && python scripts/seed_demo.py
PYTHONPATH=python uvicorn r2m_platform.main:app --host 127.0.0.1 --port 8000   # API docs: /api/v1/docs
```

The frontend lives in `web/` (Next.js). It proxies `/api/*` to `127.0.0.1:8000`.

## Demo flow (outline)

The full narrative is in [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

1. **The agent registers, but can't act yet.** OpsPilot registers its build and code-owned policies (DEPLOY-001, CAPACITY-001, DATA-001). The build is `proposed`, so its actions are denied.
2. **Release.** `run_evals.py` passes for the safe build and fails for the faulty one. The vendor submits the policies, Meridian security approves them, and the release manager evaluates and deploys.
3. **Runtime enforcement.** The degraded `payments-api` leads OpsPilot to propose a rollback, which needs exact-action approval. The reviewer approves, a single-use grant is issued, the rollback runs once, and the evidence is recorded.
4. **Faulty build.** An unguarded mutation is refused at the simulated infrastructure and raises a critical incident; the release gate blocks the faulty build.
5. **Investigate.** Use the traces, cost (simulated), coverage (observed, with its caveat), incidents and the evidence export.
6. **Reset.** `POST /api/v1/demo/agent/scenarios/{id}/reset` restores the synthetic state for the next run.

## Docs

| Doc | What |
|---|---|
| [`dev_docs/DEVELOPER_SPEC.md`](dev_docs/DEVELOPER_SPEC.md) | Product and build contract |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) | Browser API, agent hook, Keewano adapter hook |
| [`docs/SDK_CONTRACT.md`](docs/SDK_CONTRACT.md) | SDK ↔ platform wire contract |
| [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) | Tenancy, approvals, grants, integrity, known gaps |
| [`docs/TEST_MATRIX.md`](docs/TEST_MATRIX.md) | Acceptance criteria → tests |
| [`docs/HANDOVER.md`](docs/HANDOVER.md) | Per-track handover notes |
| [`db/schema-diagram.md`](db/schema-diagram.md) | Schema and lifecycles |

## Tests

```bash
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/r2m_test pytest python/tests   # disposable DB: schema is wiped
(cd python/r2m_sdk && pytest)
```
