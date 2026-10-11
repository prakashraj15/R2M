# R2M Implementation and Security Notes

**These are developer specifications and starter assets, not a functioning deployed app.** Do not run `docker compose build` until the Next.js and Python source packages described in `DEVELOPER_SPEC.md` are implemented. `compose.yaml` is a contract template, not a complete project.

## Dockerfile requirements
- Stage `web-build`: pinned Node LTS, npm ci using lockfile, Next standalone production build.
- Final stage: pinned Python 3.12+ image with Node runtime copied from a trusted matching release stage; OS trust roots installed; Python wheels and local SDK installed.
- Copy Next standalone output/static/public, API package, mock agent, scripts and SQL migrations.
- Run unprivileged user; runtime path for work files writable only as required.
- Entrypoint supervises two child processes: Python FastAPI private `127.0.0.1:8000` and Next server `0.0.0.0:3000`; trap SIGTERM, exit if either dies. Do not start `npm run dev` in container.
- Next proxy rewrite routes `/api/:path*` to `http://127.0.0.1:8000/api/:path*` and server-rendering clients use private URL.
- Healthcheck probes Next page and FastAPI `/api/v1/health/live`. Do not leak DB credentials in health output.

## Critical schema/application consistency work before implementation
- Composite consistency: validate that referenced policy revision belongs to the same agent as installation. PostgreSQL simple FKs won't imply that without composite FKs/triggers or transaction checks.
- Validate that a deployment's build.agent_id matches installation.agent_id.
- Verify all `agent_components` edges link nodes in the same installation.
- Validate runtime approval actor has customer security permission and is not creator of same policy revision.
- DB-level tests must exercise cross-tenant direct-object references; API roles alone insufficient.
- Action grant issuance and consumption must be atomic using a row lock/unique nonce with explicit expiry.
- Explicitly scope and sanitize Keewano integration events; no strings from model output forwarded unchecked.
- For historical cost metrics, distinguish total model cost from simulated cost. No claim of real cloud pricing.
- Evidence SHA-256 checksums support integrity detection but not independently verified immutability or timestamp attestation.
- If trace ingestion arrives before a run/span registration, implement robust ordering/buffer and transactional insert retries; avoid silent event loss.

## Demo identities
`Atlas Applied AI`: vendor developer and vendor release manager.  
`Meridian Financial`: customer security reviewer and customer operations viewer.  
Use seeded deterministic UUIDv5 for repeatable demo records; never hardcode production identities/tokens into frontend. Author/approver separation is enforced server-side.

## Keewano documentation references
https://docs.keewano.com/getting-started/speedhacks-quickstart  
https://docs.keewano.com/analytics/mcp-for-agents  
https://api.keewano.com/event/ingress/v1/json/swagger
