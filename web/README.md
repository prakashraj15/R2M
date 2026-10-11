# R2M mock frontend

Local Next.js App Router frontend following `../dev_docs/DEVELOPER_SPEC.md`, with white/neon-lime styling. This is frontend-only: mock identities, data, authorization, evaluations, and tool actions are not a backend or security boundary.

```sh
cd web
npm ci
npm run dev
```

Open http://127.0.0.1:3000. Node 22.20+ is recommended. No environment variables, secrets, database, model provider, or cloud accounts are required. State resets on refresh.

Expand **Demo guide** on any screen for the four-step presentation walkthrough. It tracks policy approval, safe-build deployment, a rollback request, and the action decision from shared mock state. Reset demo data restores the fixture without refreshing; the current organization and role remain selected. Pending action reviews open automatically when entering Approvals, and each action links to its exact execution trace.

## Routes and demo walkthrough

- `/`: organization overview. Switch between Atlas Applied AI and Meridian Financial.
- `/agents/opspilot`: topology with selectable nodes and inspector tabs.
- Agent sections: `/models`, `/tools`, `/orchestration`, `/storage`, `/compute`, `/policies`, `/evaluations`, `/traces`, `/security`, `/costs`, `/evidence` beneath `/agents/opspilot`.
- `/approvals`: separate queues for policy revisions and exact-action reviews. A reason is required.
- `/demo/agent`: OpsPilot's separate interface, synthetic service, scenario controls, and deterministic chat.

1. As Atlas developer, inspect the policy and architecture.
2. Switch to Meridian Financial / Security reviewer and approve DEPLOY-001 with a reason.
3. Switch to Atlas / Release manager. In Build evaluations, replay checks, evaluate release eligibility, then simulate deployment of safe-1.0. faulty-1.1 remains blocked.
4. Open OpsPilot demo, choose rollback, and send a message. The selected scenario determines the result; this is not an LLM.
5. Switch to Meridian / Security reviewer. In Approvals → Operational actions, approve the exact rollback.
6. Inspect the linked trace, updated synthetic service version, and evidence export. Refresh to reset.

`npm run typecheck`, `npm test`, and `npm run build` validate this package. Tests cover the mock's release and approval transitions, not backend security.

## Backend handoff

- `lib/types.ts` holds frontend view models; these are not a finalized copy of every wire schema.
- `lib/api.ts` is a typed integration seam for `/api/v1`. It is intentionally not used by the mock provider and never falls back to fake data after API errors.
- `next.config.ts` proxies `/api/*` to the private FastAPI listener at `http://127.0.0.1:8000` and builds standalone output. Server-side requests use server-only `R2M_INTERNAL_API_URL` with the same loopback default; this does not change the browser proxy.
- Replace `MockProvider` with authenticated server-backed state when available. Keep demo provenance explicit. Browser permission checks are presentational only.
- API handoff still needs exact approval type discrimination, action-review endpoints, DTO field mapping, pagination, and pending execution state mapping. The current DB execution enum lacks waiting/rejected states used in the UI; these may instead be derived from action records. Do not alter migrations from the frontend.
- Keep policy publication and action approval separate; real one-time grants, tenant isolation, signed sessions, and source digests must be enforced by the backend/SDK.
- Keewano remains disconnected; no live queries, ingestion, provider keys, or success claims.
- shadcn configuration and local button primitive are in place; React Flow renders topology and Recharts renders charts. Layout uses custom CSS plus Tailwind's utility pipeline.

The older HTML exploration remains in `../docs/prototypes/r2m` as a visual reference; its refund workflow is superseded.

## Backend handoff update

Checked against origin/backend. public/.gitkeep preserves Docker's copy source. Browser helpers use relative /api/v1 and cookies; api.server.ts forwards the incoming cookie to the private origin with no caching. The proxy is fixed to loopback port 8000. No public credentials were added.

/session provides a backend-connected identity picker and /me viewer, separate from local mock role controls. Product screens still need DTO adapters and endpoint wiring. Unmapped endpoint helpers intentionally return unknown instead of casting responses to mock data. See ../docs/DEMO_SCRIPT.md for the release sequence. Proposed mock builds cannot run until release evaluation and deployment complete.
