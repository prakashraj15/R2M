# Connected OpsPilot demo

The `/demo/agent` UI now calls the backend. Model replies are plain text. The mode badge comes only from the response: live, deterministic, or fallback. It does not use MockProvider or dispatch local run commands.

1. Start the backend on 127.0.0.1:8000 using its README and privately configured environment. Start `web` with `npm ci` and `npm run dev`. Choose Meridian Operations in the backend identity picker. Ask “How is payments-api doing?”. Proposed-build actions are denied. **Current branch mismatch:** the backend route inspected at origin/backend still returns 409 no_active_deployment before calling the agent if there is no deployed build. The UI displays that response; proposed-build status chat needs a backend change.
2. CI publishes the evaluation suites for safe-1.0 and faulty-1.0. In the connected Policies view, Atlas Developer submits DEPLOY-001, CAPACITY-001 and DATA-001. Meridian Security approves the revisions. Atlas Release opens Evaluations, evaluates release eligibility and deploys the eligible safe build. The UI never runs CI suites itself or invents passing results.
3. Choose Degraded to reset the backend world, then send “payments-api is throwing errors, fix it”. Inspect the returned proposal, reasons, mode, cost provenance and Keewano history. History is untrusted advisory data, not authorization. The integration toggle is shown only with the customer's integration.configure permission.
4. Follow Review in R2M to the highlighted exact-action approval. Switch to Meridian Security; review tool arguments and digest, enter a reason and approve. The UI uses can_decide from the backend.
5. Return to chat and refresh. Once the backend lists the approval as approved, Continue sends a new message. Verify the returned trace/execution IDs, ALLOW, verified and service_after. Do not treat approval alone as execution.
6. As Atlas Developer reset Faulty, then send “Run the faulty build rollback”. Render the returned denial and refused recent action; inspect Security for the real incident. Customer identities always use normal governed tools even in this scenario.
7. Open the UUID-based agent workspace to inspect real topology (including openai-llm), trace depth/timing and customer redactions, evaluations, costs by provenance, incidents and evidence integrity.

Scenario changes call reset and refetch service state; pending approvals do not disable reset. Messages are limited to 2000 characters and duplicate in-flight submissions are blocked. No message is retried after a network or server error. Explicit pre-execution 429 rate_limited responses follow Retry-After, bounded to three retries.

## Scope and validation

The root organization overview and `/agents/opspilot` legacy workspace remain an explicitly labelled mock preview. `/demo/agent`, `/approvals` and `/agents/{uuid}` use API records. No mock fallback is used on connected screens. All write requests send X-R2M-CSRF: 1; sessions are HttpOnly and inspected through /me. Secrets stay on the backend.

Real OpenAI/Keewano end-to-end verification requires the backend to be running with its private configuration. The AI team's reported verification is not a frontend test result. UI contract fixtures and local tests cannot prove a live provider call or grant enforcement.
