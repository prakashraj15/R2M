# R2M

Responsibility to Monitoring — AI governance, runtime control, evaluation, and observability.

## Frontend mock

The Next.js frontend is implemented in [`web/`](web/README.md). It includes the R2M dashboard and the OpsPilot demo, with shared mock state and the white/neon-lime design.

```sh
cd web
npm ci
npm run dev
```

Open http://127.0.0.1:3000. No secrets or external accounts are required. All data, identities, permissions, build results, and actions are simulated; state resets on refresh. The FastAPI backend, SDK, Aiven connection, and Keewano integration are not implemented by this frontend.

See [`web/README.md`](web/README.md) for routes, the demo walkthrough, validation commands, and backend handoff gaps. The implementation contract remains in [`dev_docs/DEVELOPER_SPEC.md`](dev_docs/DEVELOPER_SPEC.md).
