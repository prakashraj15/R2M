# R2M demo script

## Frontend-only rehearsal

Run `cd web` then `npm ci` and `npm run dev`. The dashboard uses local fixtures; it does not call backend services. State resets on refresh. Demo authentication, not production.

1. Atlas / Release manager: open Build evaluations. Replay the safe build checks, and compare the faulty build's mandatory failure.
2. Meridian / Security reviewer: approve DEPLOY-001 with a review reason. This publishes the policy; it does not approve any runtime action.
3. Atlas / Release manager: evaluate release eligibility for safe-1.0, then simulate deployment. A proposed build cannot run. The faulty build remains blocked.
4. Open OpsPilot, select approval-required rollback and send a message. The action waits; the service remains unchanged.
5. Meridian / Security reviewer: decide the exact runtime action in Approvals. Inspect its linked trace. Approval permits the simulated effect once; rejection leaves it unexecuted.
6. Inspect costs and evidence. Both are simulated; the export is not a backend integrity attestation.

## Connected integration sequence (backend + AI required)

All browser paths below are relative to `/api/v1`.

1. Open `/session`, load `GET /demo/identities`, select an identity through `POST /demo/session`, then obtain identity and organization permissions from `GET /me`. Never read the HttpOnly cookie.
2. AI developer registers the build and publishes build evaluation results. Registration creates a `proposed` deployment. Frontend reads evaluations; the browser does not execute CI tests.
3. Vendor developer submits the policy revision with its installation ID. Customer reviewer decides the submission.
4. Release manager calls `POST /agents/{id}/releases/evaluate` with the same installation, build version and artifact digest used by AI registration/evaluations. Display all returned checks. Only then call `POST /agents/{id}/deployments/{deployment_id}/deploy`.
5. Send `/demo/agent/message` using `scenario: approval` for the rollback story (local mock calls this `rollback`). A 503 `agent_unavailable` means the AI package has not landed; show unavailable, never fabricate a response.
6. Review the runtime action using `kind: runtime_action` and `can_decide`. Refetch state/trace after deciding: an approval alone is not evidence the tool executed.
7. Render trace depth/timestamps, customer redaction, Unknown/null metrics, cost provenance, coverage explanation and evidence integrity from API data.

## Integration status

Transport helpers exist for the supplied endpoints, plus a real session picker at `/session` and a server-only cookie-forwarding GET helper. Existing product screens still use MockProvider and require DTO adapters and API state wiring. No connected end-to-end run has been claimed. Backend source inspected on origin/backend; it has not been merged into this frontend branch.

## Updated browser contract (backend 6f7a74a)

Every browser mutation, including login/logout, sends X-R2M-CSRF: 1. The client retries explicit 429 rate_limited responses after Retry-After (seconds or HTTP date), up to three retries; persistent errors remain visible. It does not retry network or 5xx mutation failures. Server reads use the same rate-limit handling and retain the forwarded cookie. Incident updates use PATCH /incidents/{id} with status and optional note.

For connected approval demos, approval does not execute the action by itself. Send a follow-up agent message to resume the same execution/action, then refetch state and trace to confirm the actual effect. The frontend-only rehearsal simulates this completion locally and must not be presented as the connected behavior.

Allow the documented database round-trip latency in loading states; do not substitute mock success or missing values with zero. Backend runtime validation still requires privately configured server environment values and the AI package. No secrets belong in this document or frontend code.
