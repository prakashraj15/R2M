# R2M web

One Next.js codebase, built twice (`NEXT_PUBLIC_R2M_APP`):

| App | Build | Port | Proxies |
|---|---|---|---|
| R2M Control Plane | `control` | 3000 | `/api/*` → platform API (127.0.0.1:8000) |
| OpsPilot Operations Desk | `desk` | 3001 | `/agent-api/*` → OpsPilot agent API (127.0.0.1:8100) |

`NEXT_PUBLIC_CONTROL_URL` / `NEXT_PUBLIC_DESK_URL` set the cross-app links.

## Routes

Control Plane:
- `/`: organization overview (live metrics, blocked builds, Keewano status, agent registry)
- `/approvals`: review center for policy revisions and exact-action approvals
- `/agents/opspilot`: architecture; `/models`, `/tools`, `/orchestration`, `/storage`, `/compute`, `/policies`, `/evaluations`, `/traces`, `/security`, `/costs`, `/evidence`

Operations Desk:
- `/`: chat with OpsPilot about `payments-api`; every governed action goes through the R2M policy gate

Control-plane routes opened on the desk redirect to the Control Plane.

## Data

All screens read live data. `components/R2MProvider.tsx` exposes `useR2M()`; `lib/live-adapter.ts` maps API
responses to view models. The role switcher signs in as the seeded identity for that role (signed `HttpOnly`
session cookie; writes send `X-R2M-CSRF: 1`). Browser permission checks are presentational; the API enforces them.

## Commands

```bash
npm run dev        # control app on :3000 (NEXT_PUBLIC_R2M_APP=desk for the desk)
npm run typecheck
npm test
```
