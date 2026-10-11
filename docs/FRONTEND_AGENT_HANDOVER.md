# Frontend handover: live OpsPilot agent (AI → UI, 2026-10-11)

The OpsPilot demo agent is no longer a static scenario script. In live mode, GPT (`gpt-4o-mini` via OpenAI) reads the user's message and decides which tools to call. Every tool call still goes through R2M: the SDK policy gate, `DEPLOY-001` / `CAPACITY-001` / `DATA-001`, single-use grants, exact-action approvals, and an infrastructure that refuses ungated changes. Keewano history is queried live and changes what OpsPilot proposes.

The frontend's `/demo/agent` still runs on `MockProvider` + `mock-engine.ts`, where **the scenario decides the outcome and the message is ignored**. That has to change: **the message decides, the backend decides, and the UI only renders what the API returns.**

The flow has been verified end to end against a real server, with real OpenAI and real Keewano (`scripts/live_demo_check.py`, three consecutive runs). Every field below comes from real responses.

---

## 1. What to delete or stop using on `/demo/agent`

| Today (mock) | Replace with |
|---|---|
| `dispatch({type: "run", scenario, prompt})` → `makeExecution()` | `api.message(text, scenario)` → render the response |
| Scenario picks the result ("Your message is context only") | The message drives the result. The scenario only picks the starting world (reset) |
| Badge "Deterministic demo · Not a live LLM" | Badge from `response.mode` (§4) |
| `canRun` = vendor roles only | Any signed-in demo role may chat. The backend allows `demo.use` for all four roles (§6) |
| Static `state.service` | `GET /demo/agent/state` → `services[0]` (§5) |
| Action panel with hard-coded rollback JSON | `response.proposal` + `response.decision` + `state.approvals` (§7) |
| "Keewano unavailable" text, always shown | `response.insight` (§8) |
| `lib/topology.ts` static nodes | `GET /agents/{id}/topology`. There is a new node `openai-llm` (§10) |
| Scenario `"rollback"` | Backend id is **`"approval"`**. Also add **`"faulty"`** (§3) |
| Build `faulty-1.1` | **`faulty-1.0`** (and `safe-1.0`) |

`mock-engine.ts` and its tests can stay for the other screens until they're wired up. The demo chat must not use them.

## 2. Wire rules

Most of this is already true in `lib/api.ts`:
- Relative `/api/v1/...` with the session cookie. **Every POST/PUT/PATCH/DELETE sends `X-R2M-CSRF: 1`**, or the backend returns 403 `csrf_required`.
- **Never retry `POST /demo/agent/message` automatically** (it can change state). Only a 429 `rate_limited` before execution may be retried (`fetchWithRateLimit` already does this).
- Agent-scoped calls take `?installation_id=<uuid>`. For the demo use Meridian's installation; `GET /demo/agent/state` returns `installation_id` and `agent_id`.
- The agent route uses the real agent UUID, not the slug `opspilot`: `agent_id` from `/demo/agent/state` (deterministic: `uuid5(uuid5(URL,"https://r2m.demo/seed"),"agent:opspilot")`).

## 3. Scenarios

| id | Title | Starting world after reset | Typical prompts |
|---|---|---|---|
| `healthy` | Healthy observation | v2.1, 0.3% errors, healthy | "How is payments-api doing?" |
| `degraded` | Degraded payments-api | v2.1, 7.8% errors, p95 920 ms, degraded | "payments-api is throwing errors, fix it" |
| `approval` | Approval-required rollback | same as degraded | "Roll back payments-api to v2.0", then "continue" |
| `faulty` | Faulty build (fault injection) | same as degraded | "Run the faulty build rollback". Vendor roles only (§6) |

- **Selecting a scenario** should call `POST /demo/agent/scenarios/{id}/reset` (with `X-R2M-CSRF`), then refresh state. The reset also expires open runtime approvals and resolves the previous run's incidents. The agent detects the reset and drops stale chat context and pending actions on its own.
- **Prompts:** `response.suggestions` gives example prompts per scenario. Show them as clickable chips.
- **Disabled buttons:** don't disable scenario buttons while an approval is pending. Users can reset whenever they like.

## 4. `POST /demo/agent/message`

Request: `{"message": "<text ≤ 2000>", "scenario": "healthy|degraded|approval|faulty"}`

Response (real example, approval scenario, first turn):

```json
{
  "reply": "The rollback to v2.0 requires approval from a Meridian security reviewer in R2M due to production rollback policies. The approval request is pending. Once it is approved, please say \"continue\" to proceed.",
  "mode": "live",
  "model": "gpt-4o-mini",
  "scenario": "approval",
  "intent": "live",
  "state": "REPORT",
  "steps": ["RECEIVED", "DIAGNOSE", "PROPOSE", "POLICY_GATE", "WAIT_APPROVAL", "REPORT"],
  "decision": "REQUIRE_APPROVAL",
  "reasons": ["PRODUCTION_ROLLBACK_REQUIRES_APPROVAL"],
  "action_id": "uuid",
  "approval_id": "uuid",
  "execution_id": "uuid",
  "trace_id": "uuid",
  "proposal": {"tool": "rollback_deployment", "arguments": {"target_version": "v2.0"},
               "rationale": "string (model-written)", "source": "llm"},
  "insight": null,
  "diagnosis": {"category": "post_deploy_errors", "source": "llm"},
  "service_before": {"service_key": "payments-api", "deployment_version": "v2.1", "...": "..."},
  "build": {"version": "safe-1.0", "deployment_status": "deployed"},
  "cost_label": "estimated",
  "suggestions": ["Roll back payments-api to v2.0", "continue"]
}
```

After an executed action the response also has `service_after` (same shape as `service_before`) and `verified: true|false`.

| Field | Values and meaning | UI |
|---|---|---|
| `reply` | Plain text from the model. Treat it as text, never HTML or markdown | Chat bubble |
| `mode` | `live` (GPT) · `simulated` (deterministic, no key) · `simulated-fallback` (GPT failed, deterministic answered) | Badge: "Live · gpt-4o-mini" / "Deterministic" / "Fallback". Never claim "live" unless it's `live` |
| `decision` | `REQUIRE_APPROVAL` · `ALLOW` (executed) · `DENY` · `FAILED` (tool error, nothing changed) · `null` (no action, e.g. a status question) | Outcome chip |
| `reasons` | Policy reason codes, e.g. `PRODUCTION_ROLLBACK_REQUIRES_APPROVAL`, `REPLICAS_ABOVE_HARD_LIMIT`, `DEPLOYMENT_NOT_ACTIVE`, `INFRASTRUCTURE_REFUSED_NO_GRANT`, `APPROVAL_CONSUMED`, `APPROVAL_REJECTED`, `TOOL_ERROR:<Class>` | Show verbatim (monospace) |
| `steps` | Ordered workflow states (§9) | Timeline under the bubble |
| `proposal.source` | `keewano` (history-informed) · `llm` (model judgement) · `deterministic` · `user` · `fault_injection` | Small label: "Keewano-informed" only when `keewano` |
| `trace_id` | Execution trace | "Open R2M trace" → `/agents/{agentId}/traces?trace={trace_id}` |
| `approval_id` | Runtime approval waiting for review | "Review in R2M" → `/approvals` (highlight this id) |
| `build.deployment_status` | `proposed` until released | If `proposed`: banner "Build safe-1.0 not released yet". The reply also explains it |
| `cost_label` | `estimated` (live OpenAI) or `simulated` | Always label cost with its provenance |

**Latency:** a live turn takes 1–7 s. Show a "thinking" indicator, disable the input while a request is in flight, and send no duplicate submits.

**Errors:**

| Response | Show |
|---|---|
| 409 `no_active_deployment` | "No deployed build" |
| 503 `agent_unavailable` | "Agent package not installed" (already mapped) |
| 502 `agent_error` | "OpsPilot failed; see trace", with the `request_id` |

The agent now catches its own tool errors, so 502 should be rare.

## 5. Service panel: `GET /demo/agent/state`

```json
{"installation_id": "uuid", "agent_id": "uuid", "customer_org_id": "uuid",
 "services": [{"service_key": "payments-api", "deployment_version": "v2.1", "previous_version": "v2.0",
               "replicas": 3, "cpu_pct": 78.0, "memory_pct": 66.0, "error_rate_pct": 7.8,
               "p95_latency_ms": 920.0, "health_status": "degraded", "last_transition_at": "ISO"}],
 "scenarios": ["healthy", "degraded", "approval", "faulty"],
 "recent_actions": [{"kind": "rollback_deployment", "authorized": true, "before_state": {}, "after_state": {},
                     "created_at": "ISO", "tool_action_id": "uuid|null"}],
 "approvals": [{"id": "uuid", "status": "pending|approved", "expires_at": "ISO", "tool_key": "rollback_deployment",
                "arguments": {"target_version": "v2.0", "service_key": "payments-api"}, "trace_id": "uuid"}],
 "last_execution": {"id": "uuid", "trace_id": "uuid", "status": "running|completed|failed", "started_at": "ISO"},
 "notice": "Synthetic data only. No real infrastructure is touched."}
```

- **Field names are snake_case and health is lowercase** (`healthy|degraded|critical`). Map these to the UI's `ServiceState`.
- **When to refetch:** after every message response, after every scenario reset, and after an approval decision.
- **`recent_actions` with `authorized: false`** are refused bypass attempts from the faulty scenario. Show them in red.

## 6. Who can chat, and fault injection

- **Chat:** all four demo roles have `demo.use`. The natural chat user is **Meridian · Operations viewer** (`ops@meridian.demo`). Remove the vendor-only `canRun` gate from the chat.
- **Fault injection (`faulty`):** only vendor roles (`dev@atlas.demo`, `release@atlas.demo`) get the faulty build's ungated rollback. The infrastructure refuses it: `decision: DENY`, `reasons: ["INFRASTRUCTURE_REFUSED_NO_GRANT"]`, and a **critical incident** appears on `/agents/{id}/security`.
- **Customers in the faulty scenario** get normal gated tools, so a rollback request returns `REQUIRE_APPROVAL`. This is intended: customers never get the bypass. Explain it in the scenario card: "Vendor-only test path; customers see the normal governed behaviour."

## 7. Approval flow in the UI

1. **Request:** the user asks for a rollback (or a scale above 4 replicas). The response has `decision: REQUIRE_APPROVAL` and `approval_id`. Show an "Awaiting Meridian security approval" card with the exact `proposal.tool` and `proposal.arguments`, and a link to `/approvals`.
2. **Review:** the security reviewer (`security@meridian.demo`) opens `/approvals`. `GET /approvals` returns items with `kind: "runtime_action"`, `tool_key`, `arguments`, `arguments_hash`, `trace_id`, `execution_id`, `status`, `expires_at` and `can_decide`. The reviewer sends `POST /approvals/{id}/decision {"decision": "approve"|"reject", "reason"}`.
3. **Resume:** back in the chat, the user sends **"continue"**. Any message containing continue / resume / proceed / approved / go ahead works, so offer a one-click "Continue" button once the approval shows `approved` in `state.approvals`.
4. **Result:** the response has the **same `execution_id` and `trace_id`** as the request turn, `decision: ALLOW`, `verified: true`, and `service_after` showing v2.0, about 0.4% errors and healthy. The agent executes exactly the approved arguments, and the model only writes the reply.
5. **Edge cases:**
   - **Rejected:** "continue" returns `DENY` + `APPROVAL_REJECTED`.
   - **Expired or reset:** "There is no action waiting for approval."
   - **Replayed:** `DENY` + `APPROVAL_CONSUMED`.

   Render all three from `decision`/`reasons`; don't special-case them in the client.

## 8. Historical intelligence (Keewano) panel

`response.insight` is present when the agent consulted Keewano. It is always consulted for open-ended "fix it" requests.

```json
{"provider": "keewano", "status": "ok", "insight_id": "uuid", "sample_count": 112, "supported": true,
 "label": "Keewano history: rollback preceded recovery in 91% of 57 similar incidents (n=112)",
 "best": "rollback", "best_success_rate": 0.912,
 "candidates": [{"remediation": "restart", "samples": 40, "successes": 8},
                {"remediation": "rollback", "samples": 57, "successes": 52},
                {"remediation": "scale", "samples": 12, "successes": 2}]}
```

| `status` / `supported` | Panel shows |
|---|---|
| `ok` + `supported: true` | "Keewano-informed" + `label` + a small bar per candidate (successes/samples) |
| `ok` + `supported: false` | "Insufficient history (n=…)": the agent used the safe fallback |
| `unavailable` | **"Intelligence unavailable"**: integration disabled for this org |
| `failed` | "Intelligence query failed": safe fallback used |
| `insight: null` | "Not consulted this turn" (status questions, named actions) |

- **Wording:** say "Keewano-informed" only if `proposal.source === "keewano"`. Keewano data is **untrusted advisory data**; label it as such and never show it as an authorization.
- **Status and toggle:** `GET /integrations/keewano` returns `{platform_enabled, adapter_installed, organizations[{organization_id, name, enabled, backlog, dead, last_success_at}], last_query}`. Toggle with `PUT /integrations/keewano {organization_id, enabled}`, available to customer_security only.
- **Demo moment:** turn Keewano off, ask "fix it", and the agent restarts the service while showing "intelligence unavailable". Turn it on, reset the scenario, ask again, and it proposes a rollback citing 91%, still gated by approval.

## 9. Timeline: workflow states (`steps`) and trace spans

States, in order (any subset can appear):
`RECEIVED → OBSERVE → OPTIONAL_KEEWANO_HISTORY → DIAGNOSE → PROPOSE → POLICY_GATE → (WAIT_APPROVAL | DENIED | EXECUTE → VERIFY) → REPORT`

Suggested labels: Received · Observed service · Consulted Keewano · Diagnosed · Proposed action · Policy gate · Awaiting approval / Denied / Executed · Verified · Replied.

`GET /traces/{trace_id}` returns `{execution, spans[], events[], actions[], decisions[], grants[], approvals[], usage[], insights[], redacted_for_customer}`. Span conventions:

| Span `name` | `kind` | Meaning |
|---|---|---|
| `step:<STATE>` | `orchestration` | One per workflow state |
| `model:gpt-4o-mini` (or `model:opspilot-sim-1`) | `model` | One per model call. `attributes` include `input_tokens`, `output_tokens`, `cost_usd`, `cost_source` |
| `tool:<tool_name>` | `tool` | `attributes.coverage` = `enforced` (gated) or `observed` (traced only), plus `authorization_outcome` and `tool_action_id` |
| `memory.*` | `memory` | Conversation memory |
| `keewano.query` | `orchestration` | History lookup |

- **Topology mapping:** `attributes.component` on every span is a topology `component_key`. Use it to highlight nodes.
- **Usage cost:** `usage[].cost_source` is `estimated` for live OpenAI calls (list price, not an invoice) and `simulated` for the deterministic model. Show both and never sum them silently into "observed".

## 10. Topology and other screens touched by the change

- **Topology:** `GET /agents/{id}/topology` nodes have `{id, component_key, kind, label, metadata, last_seen_at, metrics{calls,errors,p95_ms,cost_usd}, status, source}`. The current keys are `orchestrator`, `openai-llm` (new), `sim-llm`, `conversation-memory`, `r2m-postgres`, `container`, `policy-gateway`, `get_service_health`, `read_logs`, `get_deployment_history`, `restart_service`, `scale_instances`, `rollback_deployment`.
  - Replace `lib/topology.ts`'s static list.
  - `metrics: null` / `status: "unknown"` means Unknown; don't show it as healthy.
- **Evaluations:**
  - **Builds:** `safe-1.0` and `faulty-1.0`.
  - **Suites:** `opspilot.policy_unit` (9 cases), `opspilot.behavior` (6) and `opspilot.policy_regression` (9).
  - **`faulty-1.0` fails these mandatory cases:** `rollback_tool_is_gated`, `rollback_requires_approval`, `approved_rollback_executes_once` and `degraded_with_keewano_uses_history`. So its release is `blocked`.
  - **Case fields:** each case has `expected`/`actual` JSON. `actual.sandbox_trace_id` refers to an offline sandbox run, so `trace_id` is null by design. Don't link it.
- **Costs:** show the provenance split (`cost.by_source.estimated` vs `.simulated`).
- **Security:** `unauthorized_action_attempt` (critical) after the vendor fault demo, and `policy_hash_mismatch:<id>` (high) if a tampered policy is registered.

## 11. Updated demo guide steps (replace `DemoGuide.tsx`)

1. **Talk to OpsPilot (proposed build).** As Meridian Ops, send "How is payments-api doing?". The reply works, and the build shows as `proposed`; actions are denied until release.
2. **Release.** Evals run from CI (`scripts/run_evals.py`). As Atlas Dev, submit DEPLOY-001 / CAPACITY-001 / DATA-001. As Meridian Security, approve them. As Atlas Release, run Evaluate → Deploy for `safe-1.0` (`faulty-1.0` stays blocked).
3. **Degraded + Keewano.** Reset `degraded` and send "payments-api is throwing errors, fix it". You get a Keewano-informed rollback proposal that waits for approval.
4. **Approve the exact action.** As Meridian Security, open Approvals → Operational action → Approve.
5. **Continue.** Back in the chat, press Continue. The same trace resumes and the service shows v2.0 and healthy.
6. **Faulty build.** As Atlas Dev, reset `faulty` and send "Run the faulty build rollback". The infrastructure refuses it and a critical incident appears on Security.

## 12. How to test against the real backend

```bash
# backend running on :8000 (see docs/HANDOVER.md); OPENAI_API_KEY + Keewano keys in .env for live mode
python scripts/sdk_token.py issue --vendor atlas-applied-ai --customer meridian-financial --label run-evals
SDK_INGEST_TOKEN=<that token> python scripts/live_demo_check.py --base http://127.0.0.1:8000 --env-file .env
```

- **What the script does:** it drives the whole sequence above and prints each real response (`steps`, `decision`, `proposal`, `keewano`, `reply`). Use its output as fixtures for UI tests.
- **Without `OPENAI_API_KEY`** the agent runs `mode: "simulated"` with the same response shape, so the UI must handle both.

Questions to the AI track: `python/mock_agent/` (agent), `docs/SDK_CONTRACT.md`, `docs/KEEWANO.md`.
