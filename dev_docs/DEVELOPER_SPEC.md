# R2M — Developer Implementation Specification v1.0

**Status:** hackathon prototype build contract  
**Product:** R2M (Responsibility to Monitoring)  
**Date:** 2026-10-11  
**Primary audiences:** implementation agents, frontend/backend engineers, SDK developer, reviewer

## 0. Non-negotiable product definition

R2M is an **AI governance, runtime control, evidence, evaluation, cost, and observability platform**, not only an observability product. It serves (1) internal teams deploying their own agents, and (2) AI vendors deploying agents for enterprise customers whose security reviewers want independently verifiable controls.

The prototype must demonstrate a complete chain:
`vendor agent and code-owned policy -> build evaluation -> customer security approval -> deployment eligibility -> agent tool action -> runtime enforcement -> native trace and immutable-ish evidence -> optional Keewano historical analytics -> dashboard investigation`.

Do not claim that an SDK alone prevents bypasses when the host application can call uninstrumented tools. Identify observed versus proven coverage.

## 1. Locked choices, constraints, and scope

- **One Docker image / one Docker container / one exposed public port `3000`.** Inside the container run production Next.js and one Python FastAPI process. Next.js proxies `/api/*` to the private Python listener on `127.0.0.1:8000`. No other ports published. A tiny supervisor/entrypoint terminates the container if either critical process exits. No dependency on systemd.
- **Two UIs served from the same Next.js app:** R2M multi-organization dashboard and OpsPilot demonstrator mini-interface at `/demo/agent`. Demo UI is *not* a separate backend or separate exposed port.
- **PostgreSQL** hosted on user's **Aiven** account, accessed over verified TLS. No local Postgres container. Use `asyncpg`, raw parameterized SQL and versioned migrations. Secrets provided through environment at runtime only.
- **Python R2M SDK** is a separately installable local package, imported by the mock agent even though prototype code runs in same Python server. Never permit SDK to import internal web handlers or database modules. SDK uses its own HTTP transport to the platform API via `http://127.0.0.1:8000` (loopback). Do not shortcut by directly writing DB.
- **Mock agent:** OpsPilot, an AI operations assistant deployed by synthetic vendor **Atlas Applied AI** into synthetic customer **Meridian Financial**, with deterministic mocked model and simulated payment-service infrastructure. Tools operate only on synthetic records; never issue real rollout/restart/rollback commands.
- **Policies defined as Python code alongside the agent**, registered with the SDK; dashboard stores metadata, activation grants, approvals and hashes, not editable executable source. Policy decisions enforced in the agent's SDK guarded tool path. Version/hash mismatch means sensitive actions fail closed.
- **Evaluations are pre-deployment only** (unit/integration/behavioral/policy regression), and must gate deployment eligibility. At runtime, enforce and monitor policies; do not execute eval test suites against production traffic.
- **R2M native trace layer** collects spans, events, policy decisions, resource usage, incidents and evidence. Keewano is an *optional hosted event analytics subscription*, not the trace store. The rest of the app must work with Keewano disabled, but the hackathon flow must prove a live Keewano answer materially changes the remediation recommendation.
- **No Sparta integration**. No Redis/Kafka/Celery/OTel infrastructure mandatory. No real model vendor, payment provider, cloud IAM, enterprise SSO or destructive infrastructure integration in MVP.
- **Demo roles:** Vendor Developer, Vendor Release Manager, Customer Security Reviewer, Customer Operations Viewer. Demo switching is visually convenient, but every sensitive backend operation must still check a signed demo session and role/organization scope. Clearly label demo auth as non-production.
- **No production-grade audit/compliance certification claims.** This is demonstrable engineering evidence, not SOC 2, ISO 27001 or legal audit attestation.

### 1.1 System boundaries

**R2M platform owns:** agent registry, orgs/deployments, policy registry and approvals, test run result ingestion, release gates, trace ingestion/storage/query, incidents, cost/latency, evidence compilation, Keewano adapter configuration/query, dashboard.

**Agent + SDK own:** model/tool instrumentation, orchestration spans, code-based policy evaluation, gated actions, execution reports, simulated infrastructure actions, synthetic incident state.

**Keewano owns:** optional cross-execution typed-event analytics. Never send full prompts, secrets, PII or raw logs. Query outputs are advisory and cannot authorize an action contrary to R2M policies.

## 2. Repository layout (implement exactly; `__init__.py` in Python packages)

```text
r2m/
├── README.md                         # one-command setup, demo walkthrough, API docs links
├── DEVELOPER_SPEC.md                 # this contract
├── .env.example                      # all public runtime/config variable names, no secrets
├── .gitignore                        # .env, caches, node_modules, .next, coverage, build
├── compose.yaml                      # ONE platform service, build and health check
├── Dockerfile                        # multi-stage JS build + Python setup, final combined image
├── docker/
│   ├── entrypoint.sh                 # starts api and web, forwards signals, exits on child death
│   └── healthcheck.py                # probes private API and public Next port
├── scripts/
│   ├── init_db.py                    # applies SQL migrations idempotently
│   ├── seed_demo.py                  # idempotent fake orgs, identities, agent and policies
│   ├── run_evals.py                  # deterministic CI run, writes evaluation evidence
│   ├── seed_keewano.py               # optional backfill; disabled unless explicitly invoked
│   └── smoke_test.py                 # HTTP smoke tests and authorization negative tests
├── db/
│   ├── migrations/
│   │   └── 0001_initial.sql          # schema supplied separately in SCHEMA.sql
│   ├── seeds/README.md               # seed rules and deterministic IDs
│   └── schema-diagram.md             # ERD and lifecycle notes
├── web/
│   ├── package.json                  # pinned Next, React, Tailwind, shadcn, xyflow, Recharts
│   ├── package-lock.json             # npm lockfile
│   ├── next.config.ts                # reverse proxy rewrites; standalone output
│   ├── tsconfig.json
│   ├── postcss.config.mjs
│   ├── components.json               # shadcn registry settings
│   ├── app/
│   │   ├── layout.tsx                # organization/role-aware shell
│   │   ├── page.tsx                  # / org overview
│   │   ├── agents/[agentId]/page.tsx # selected-agent workspace topology
│   │   ├── agents/[agentId]/policies/page.tsx
│   │   ├── agents/[agentId]/evaluations/page.tsx
│   │   ├── agents/[agentId]/traces/page.tsx
│   │   ├── agents/[agentId]/security/page.tsx
│   │   ├── agents/[agentId]/costs/page.tsx
│   │   ├── agents/[agentId]/evidence/page.tsx
│   │   ├── approvals/page.tsx        # reviewer queue and decisions
│   │   └── demo/agent/page.tsx       # second UI: OpsPilot chat + fault scenario controls
│   ├── components/
│   │   ├── navigation/{OrgSwitcher,RoleSwitcher,Sidebar}.tsx
│   │   ├── agents/{AgentCard,AgentTopology,NodeInspector}.tsx
│   │   ├── policy/{PolicyTable,PolicyDetail,ApprovalPanel}.tsx
│   │   ├── traces/{TraceWaterfall,EventDetail}.tsx
│   │   ├── metrics/{MetricCard,CostChart}.tsx
│   │   └── demo/{AgentChat,ScenarioControls,SimulatedServiceStatus}.tsx
│   ├── lib/{api.ts,types.ts,format.ts,permissions.ts} # typed fetch, response types
│   └── styles/globals.css
├── python/
│   ├── pyproject.toml                # FastAPI, uvicorn, asyncpg, httpx, pytest, psutil
│   ├── r2m_platform/
│   │   ├── main.py                   # FastAPI startup, routers, lifespan
│   │   ├── config.py                 # typed env validation; fail on absent required secrets
│   │   ├── database.py               # asyncpg connection pool; TLS required
│   │   ├── auth.py                   # signed demo sessions, RBAC, tenant context
│   │   ├── dependencies.py           # injectable DB, auth, services
│   │   ├── errors.py                 # structured API errors, safe messages
│   │   ├── schemas/                  # Pydantic request/response contracts
│   │   ├── routers/
│   │   │   ├── health.py             # liveness/readiness
│   │   │   ├── demo_auth.py         # demo login/switch identity
│   │   │   ├── organizations.py
│   │   │   ├── agents.py
│   │   │   ├── deployments.py
│   │   │   ├── policies.py
│   │   │   ├── approvals.py
│   │   │   ├── evaluations.py
│   │   │   ├── traces.py
│   │   │   ├── metrics.py
│   │   │   ├── incidents.py
│   │   │   ├── evidence.py
│   │   │   ├── integrations.py
│   │   │   └── demo_agent.py
│   │   ├── services/
│   │   │   ├── registry.py           # registration and versioning
│   │   │   ├── policy_registry.py    # hash, binding and approval state
│   │   │   ├── authorization.py      # scope checks, activation receipts
│   │   │   ├── release_gate.py       # eval + policy + approval decision
│   │   │   ├── trace_ingest.py       # dedup/validation/parent span correlation
│   │   │   ├── metrics_rollup.py     # dashboard calculations from raw facts
│   │   │   ├── evidence_builder.py   # artifact references + SHA-256
│   │   │   ├── incident_detector.py  # production rule/violation alerts
│   │   │   └── keewano_adapter.py    # optional ingestion/MCP with timeout/retry
│   │   └── workers/{event_outbox.py,rollups.py} # background in-process tasks
│   ├── r2m_sdk/                      # separate package; installable independently
│   │   ├── pyproject.toml
│   │   ├── src/r2m/
│   │   │   ├── __init__.py            # public API only
│   │   │   ├── client.py              # R2M client and agent registration
│   │   │   ├── context.py             # contextvars trace/execution propagation
│   │   │   ├── tracing.py             # sync/async spans, exception capture
│   │   │   ├── tool.py                # protected tool decorator
│   │   │   ├── model.py               # model invocation recording
│   │   │   ├── policy.py              # typed policies and version hashes
│   │   │   ├── approvals.py           # exact-action approval binding
│   │   │   ├── usage.py               # estimated cost and latency
│   │   │   ├── transport.py           # HTTP, background buffer, retries
│   │   │   └── types.py               # enums, event schemas, decision types
│   │   └── tests/
│   ├── mock_agent/
│   │   ├── __init__.py
│   │   ├── agent.py                   # deterministic intent+plan+state machine
│   │   ├── llm.py                     # simulated model and token usage
│   │   ├── workflow.py                # observe->diagnose->propose->authorize->act
│   │   ├── service_state.py           # synthetic deployments, replica count, error rate
│   │   ├── policy/
│   │   │   ├── deployment.py          # rollback approval policy
│   │   │   └── scaling.py             # max replica policy
│   │   ├── tools/
│   │   │   ├── health.py              # get_service_health
│   │   │   ├── logs.py                # read sanitized logs
│   │   │   ├── restart.py             # controlled local fake restart
│   │   │   ├── scale.py               # guarded scale_instances
│   │   │   └── rollback.py            # guarded rollback_deployment
│   │   ├── scenarios.py              # normal, degraded, approval, bypass-test
│   │   └── tests/                     # unit/integration/policy/eval fixtures
│   └── tests/                         # platform authorization, API, ingestion
└── docs/
    ├── API_CONTRACT.md                # documented endpoints, examples, error codes
    ├── SDK_CONTRACT.md                # decorators, startup, transport, failure policy
    ├── SECURITY_MODEL.md              # org tenancy, approvals, isolation, threat model
    ├── DEMO_SCRIPT.md                 # two-role end-to-end hackathon narrative
    ├── KEEWANO.md                     # typed events / MCP workflow / integration setup
    └── TEST_MATRIX.md                 # pass criteria; negative and fault-injection tests
```

**Rule:** API web routes only validate/authorize/dispatch; business logic belongs in `services/`. `r2m_sdk` must not import `r2m_platform`, `db`, or `mock_agent`. `mock_agent` imports only the public SDK API. UI data comes from backend, not invented hardcoded metrics (seeded data clearly labeled demo).

## 3. Environment variables

`.env.example` is canonical. Separate secret from non-secret values; never check `.env` into git. Docker Compose uses `env_file`, but `.env` used for Compose interpolation must be handled distinctly. Frontend should never receive Aiven or Keewano secrets. The only `NEXT_PUBLIC_` variable is a benign title/build label, if needed.

Required when mode=`demo`: `APP_ENV`, `DATABASE_URL`, `SESSION_SIGNING_KEY`, `SDK_INGEST_TOKEN`, `R2M_INTERNAL_API_URL`. Keewano optional when disabled; required when enabled: `KEEWANO_API_KEY`, `KEEWANO_PAT`, base URL settings. Require TLS for remote Aiven; use `DATABASE_SSL_MODE=verify-full` plus trusted CA configuration if needed. Never silently downgrade SSL verification.

See **`.env.example`** for complete names, defaults, comments and whether each is secret. Never log connection strings or tokens.

## 4. API contracts (all under `/api/v1`)

Use JSON ISO 8601 UTC times, UUID primary IDs, pagination (`limit`, `cursor`), `X-Request-ID` echo, tenant-scoped queries, structured errors `{code,message,request_id}`. Browser authentication via signed HttpOnly SameSite=Lax cookie; SDK ingestion via bearer token over loopback (future deployment requires TLS). Reject organization IDs supplied by a caller when outside accessible scope.

| Method | Path | Use / authorization |
|---|---|---|
| GET | `/health/live` | liveness (no DB), unauthenticated |
| GET | `/health/ready` | DB-ready (minimal safe payload), internal or bounded unauthenticated |
| POST | `/demo/session` | select allowlisted seeded demo identity; issues signed session |
| GET | `/me` | actor, organizations, roles, permissions |
| GET | `/organizations` | accessible tenants only |
| GET | `/organizations/{orgId}/overview` | metrics and monitored agents scoped to customer/vendor relation |
| GET/POST | `/agents` | list/register; vendor developer POST; scoped GET |
| GET | `/agents/{agentId}/topology` | inventory of models, tools, memory, compute, graph edges |
| GET | `/agents/{agentId}/deployments` | scoped version/hash/status |
| POST | `/agents/{agentId}/releases/evaluate` | vendor release role; triggers offline suite only on simulated environment |
| GET | `/agents/{agentId}/evaluations` | build test list, evidence references |
| GET | `/agents/{agentId}/policies` | manifest/hashes/owners/revisions |
| POST | `/agents/{agentId}/policies/register` | authenticated SDK; exact version+hash |
| POST | `/agents/{agentId}/policies/{policyId}/submit` | vendor submits immutable revision for customer review |
| GET | `/approvals` | reviewers see assigned requests |
| POST | `/approvals/{id}/decision` | customer security reviewer; reject self-approval |
| POST | `/actions/authorize` | SDK runtime action gate; checks approved policy hash, action payload digest, grant, environment |
| POST | `/actions/{actionId}/result` | SDK reports real outcome after authorized execution |
| POST | `/ingest/events` | SDK event ingestion with schema validation + deduplication |
| GET | `/agents/{agentId}/traces` | paginated run list |
| GET | `/traces/{traceId}` | full tree, events, decision links, redacted payload |
| GET | `/agents/{agentId}/metrics` | bounded time ranges, actual aggregated values |
| GET | `/agents/{agentId}/incidents` | security and operational findings |
| GET | `/agents/{agentId}/evidence` | linked artifact/evaluation/policy/deployment records |
| GET | `/integrations/keewano` | status + last sync/query; no secrets |
| POST | `/integrations/keewano/query` | authorized analyst only; bounded query, results treated untrusted |
| POST | `/demo/agent/message` | deterministic simulated chat, produces SDK traces |
| POST | `/demo/agent/scenarios/{scenarioId}/reset` | reset only demo synthetic state; privileged demo mode |
| GET | `/demo/agent/state` | simulated service state and demo controls |

`POST /actions/authorize` must return typed `ALLOW | DENY | REQUIRE_APPROVAL`, reason codes, policy ID/hash, decision ID and **short-lived action-bound grant** when allowed. Grant binds org, deployment, policy revision, tool, canonical argument hash, execution ID, expiry, and single-use nonce. Runtime tool must verify before action. The UI approval of a policy revision is **not** approval for every future operational action.

## 5. Native traceability: event and span contract

Every SDK event carries: `event_id` (UUID), `schema_version`, `occurred_at`, `received_at` (server), `vendor_org_id`, `customer_org_id`, `agent_id`, `deployment_id`, `execution_id`, `trace_id`, `span_id` (nullable for execution-level events), `parent_span_id`, `kind`, `name`, `severity`, `status`, `duration_ms`, `attributes` (allowlisted/redacted), `request_id`. For policy events also `policy_revision_id`, `decision_id`, `tool_action_id`, `authorization_outcome`; for evaluation, `suite_id`, `test_case_id`, `build_id`; for measured usage, currency, provider and measurement kind.

- Stable `event_id` makes retries idempotent (`ON CONFLICT DO NOTHING`). Preserve chronological timestamps and store ingestion time separately. Don't assume network arrival order.
- `spans` rows model trees; `execution_events` model discrete changes; policy decisions and approvals are separate indexed tables.
- Only sampled/redacted input/output metadata by default. Optional payload capture is disabled for MVP. Never send credentials, customer data, access tokens or full stack traces to Keewano.
- Cost labels: `observed`, `estimated`, `allocated`, `simulated`; mocked model usage/cost must be marked `simulated` on every visual.
- Healthy / Degraded / Critical / Unknown states are derived from heartbeat freshness, errors, and coverage. Missing events = **Unknown**, not healthy. An intended policy DENY is not automatically a system failure.
- Platform controls resource retention: defaults demo 30 days; evidence references may remain longer, but do not pretend Postgres is immutable WORM storage.

## 6. Policies, approvals, and build/evaluation gating

**Policy declaration:** at agent import, Python function+static metadata (`id`, semver version, description, enforcement point, scope, owner). Compute a reproducible artifact digest from packaged source/build manifest (do not hash `repr(function)` or unstable introspection strings). Ingest policy artifact hash and evaluate against approved version. Locally prevent sensitive tool execution if required activation cannot be verified.

**Approval:** vendor developer submits a policy revision + affected tools + test results; customer security reviewer approves exact hash for exact customer org/environment/agent deployment. Author cannot approve their own request. A revoked or superseded revision cannot remain active. Record actor, timestamp, reason, version and irreversible audit event.

**Predeploy evaluation:** command `python scripts/run_evals.py --agent opspilot --build VERSION` runs deterministic unit/integration + security scenarios against reset synthetic state. Store suite/test expected vs actual, score/result, trace IDs, compiled source/test hashes and build identity. Failed mandatory test => release not eligible. A passed test alone doesn't override customer approval. Release gate requires `build_evals_passed AND required_policies_approved AND artifact_hash_matches AND tenant_access_valid`.

**Production:** policy enforcement, tracing, cost/latency, incident detection; no continuous CI eval. Don't use Keewano aggregate output as an enforcement substitute.

## 7. OpsPilot mock agent

### 7.1 Simulated world

Synthetic customer `Meridian Financial` has service `payments-api` with state: `service_id`, `environment`, `deployment_version`, `previous_version`, `replicas`, `cpu_pct`, `memory_pct`, `error_rate_pct`, `p95_latency_ms`, `health_status`, `last_transition_at`. Seeded incident after version 2.1 (elevated error rate). **No commands to any host Docker daemon or real cloud API.** State changes are confined to `simulation_services` and `simulation_actions` tables scoped to customer org.

### 7.2 Deterministic steps

`RECEIVED -> OBSERVE -> DIAGNOSE -> (OPTIONAL_KEEWANO_HISTORY) -> PROPOSE -> POLICY_GATE -> (WAIT_APPROVAL | DENIED | EXECUTE) -> VERIFY -> REPORT`.

Every transition emits native trace event and span; failed tool calls emit error class and retry outcome. No magic path that reads only dashboard fixtures. Users choose scenario and send a prompt in the mini UI; deterministic agent maps intents to this finite state machine.

Tools: `get_service_health()`, `read_logs()` (fake sanitized messages), `get_deployment_history()`, `restart_service()` (low risk), `scale_instances(desired_replicas)`, `rollback_deployment(target_version)` (high risk). Store arguments, action IDs, latency and effect in synthetic tables. Return structured results.

**Policy `DEPLOY-001`**: production rollback requires exact-action human approval; **`CAPACITY-001`**: scaling over 4 replicas requires approval; **`DATA-001`**: do not return secrets/unredacted customer identifiers from logs.

### 7.3 Four showcase scenarios

1. **Healthy observation:** read health and history, reply without mutation; native traces and simulated cost.
2. **Degraded payments-api:** ask Keewano which past remediation category correlated with recovery; choose suggestion based on actual live result when integration enabled; still enforce policy. When Keewano unavailable, show `intelligence unavailable` and deterministic safe fallback; do not claim a Keewano-informed recommendation.
3. **Approval-required rollback:** agent proposes rollback, SDK returns REQUIRE_APPROVAL, create operational approval ticket, reviewer approves exact action, SDK gets one-time grant, simulated rollback succeeds, captures evidence.
4. **Faulty build:** an intentionally unguarded rollback route exists only in eval fixture or fault-injection test environment. A simulation action event proves authorization missing; mandatory regression test fails and release is blocked. Ensure **normal runtime never offers this bypass toggle to an unauthorized customer**.

### 7.4 Keewano hackathon loop

Integration in `r2m_platform/services/keewano_adapter.py`, never in the SDK's required core. SDK publishes R2M internal events; platform optional outbox mirrors select typed events to Keewano. Register custom event IDs >=2000 once with immutable data types; entity key a deterministic UUIDv5 for the relevant agent deployment or incident grouping; send ordered events and `dataSessionId`+batch id to REST ingestion. Event sets (illustrative IDs, frozen once registered):

| ID | Event name | Type | Data |
|----|------------|------|------|
| 2000 | DeploymentVersion | string | `v2.1` |
| 2001 | IncidentCategory | string | `post_deploy_errors` |
| 2002 | RemediationProposed | string | `restart`/`rollback`/`scale` |
| 2003 | RemediationSucceeded | bool | true/false |
| 2004 | PolicyOutcome | string | `allow`/`deny`/`approval_required` |
| 2005 | ToolFailureClass | string | `timeout`/`permission` |
| 2006 | ExecutionLatencyMs | uint | nonnegative integer |
| 2007 | BuildEvaluationPassed | bool | true/false |

**Keewano official references:** quickstart `https://docs.keewano.com/getting-started/speedhacks-quickstart`, REST `https://api.keewano.com/event/ingress/v1/json/in`, registration path `/event/ingress/v1/json/custom`, MCP `https://api.keewano.com/mcp` with header `k-token` set to personal access token. Separate **API key for ingestion** from **PAT for MCP**. Keewano has an indexing delay of around five minutes; send backfilled realistic historical events via REST before demo, then live events and live MCP query. MCP query must return actual results, not hardcoded advice. Validate its current tool discovery/protocol at implementation; do not invent tool names. Query results are untrusted advisory data.

**Business logic coupling:** when queried historical remediation success is sufficiently supported, suggest best candidate; if sample size too low/no result, favor safe diagnose/escalate. Record `insight_id`, query id, result summary, sample count and proposed action. Never bypass `DEPLOY-001` based on Keewano output.

**Subscription:** admin can enable/disable Keewano in integration settings; if disabled all internal R2M monitoring/eval works. Keewano key must be server-side and scoped per integration/tenant where practical. For the hackathon one explicitly labeled demo project is acceptable, with tenant IDs encoded safely into grouping (not raw PII).

## 8. Screen contracts

### 8.1 R2M organization overview (`/`)

Top bar org switcher, perspective/role badge, 24h time filter, integration health. Six metrics: deployed agents, run success, unresolved high-severity findings, policy enforcement coverage (observed denominator explained), cost total with provenance, p95 action latency. Registry lists agent, deployment, status, violations, eval gate, cost; click OpsPilot.

### 8.2 Agent workspace (`/agents/:id`)

Left sidebar: Overview, Architecture, Models, Tools, Orchestration, Memory & Storage, Compute, Policies, Evaluations, Observability, Security, Costs, Evidence. Center canvas topology with real nodes/edges and Healthy/Degraded/Critical/Unknown. Right-click or select node opens inspector: Metrics, Events, Policies, Configuration; show calls/errors/p95/cost/source. Trace waterfall is execution path; no static fake graphs after seed.

### 8.3 Policy page

Drata-inspired inventory: policies, status, creator, updated time, version, approver, next review, assigned agents and approved deployments. Policy detail shows description, code artifact hash, tests, requested permissions, owner, reviewer, approval history, operational decisions, linked evidence, coverage caveat. Customer security can approve submitted policies, not edit vendor code.

### 8.4 Evaluations page

**Build/CI only.** Table build, commit/digest, suite, number pass/fail, mandatory failure, gate result, timestamp. Drill down test case -> expected vs actual, trace and policy revision. Failed build badge must block demo deployment action. Runtime findings belong Security/Observability, not evaluation suites.

### 8.5 Two actor perspectives

Vendor Developer: operational topology, traces, SDK, model/tool metrics, propose policy, submit release. Customer Security Reviewer: scope permissions, approvals, failed security tests, provenance, enforcement evidence, audit export. Both share database records with organization-scoped RBAC. Reviewers get redacted evidence, not proprietary prompts or all vendor source.

### 8.6 Agent mini UI (`/demo/agent`)

Separate navigation shell within same Next.js app. Left: simulated service health and scenario selector. Center: chat and timeline. Right: proposed tool action, approval status and last R2M execution ID; hyperlink opens R2M agent trace. Role switching also applies backend access.

## 9. Database invariants

Schema in `SCHEMA.sql` below is the authoritative migration starting point. Tables group: identities + multi-org RBAC; agents+deployments+topology; policy source revisions+approvals+activation; builds/evaluations; execution/spans/events/action decisions; cost/metric points; findings/evidence; simulation state; integration config+outbox; audit.

- All tenant-owned records carry `customer_org_id` and/or join to an owner, and DB queries include the scope; consider Postgres RLS in production but not a substitute for API permission checks.
- External integration credentials live only in env/secret manager, never plaintext in DB. `integration_configs` stores enablement and public metadata, not API key.
- `audit_events` append-only at application level; do not expose update/delete endpoints.
- A policy's code digest and a deployment artifact digest must be stored separately. Approval bound to policy digest and customer scope. Dedupe ingestion events by `event_id`; record checksums for evidence artifacts.
- An authorized action is not the same as a successful action. Persist attempted, authorized, executed and verified timestamps separately.
- Do not call a control "verified" simply because test cases passed; show last deployment attestation, last runtime observation, and unknown coverage explicitly.

## 10. Local build and execution

1. Copy `.env.example` to `.env`, set Aiven DB URL/TLS trust, long random session and SDK tokens. Keep Keewano keys blank with `KEEWANO_ENABLED=false` until ready.
2. `docker compose build`; `docker compose up -d`. Compose maps host 3000 to container 3000; nothing else.
3. `docker compose exec r2m python scripts/init_db.py`, then `docker compose exec r2m python scripts/seed_demo.py`.
4. Visit `http://localhost:3000`, sign in as allowlisted demo identities and inspect both UIs.
5. `docker compose exec r2m python scripts/run_evals.py --agent opspilot --build safe-1.0`, then faulty build; confirm safe eligible and faulty blocked.
6. Optional Keewano: create Keewano project and API/PAT, set `KEEWANO_ENABLED=true`, run `scripts/seed_keewano.py`, wait for indexing, validate live MCP query and effect on OpsPilot recommendation.
7. Execute both protected and denied scenarios and examine traces, approval, release gate, evidence, costs. `docker compose down` leaves hosted Aiven data untouched.

## 11. Exact build order (avoid parallel half-implementations)

**Milestone A — skeleton:** repository, Docker, Next proxy, FastAPI health, env validation, Aiven pool, migration runner. Acceptance: one public port, one healthy container, SQL migrations apply.

**Milestone B — identity/registry/screens:** orgs and roles, seeded vendor/customer, agent registry, two UIs, topology static structure populated from DB. Acceptance: customer cannot access unrelated tenant API records; both UIs accessible via same origin.

**Milestone C — SDK/trace:** standalone SDK with sync/async decorators, execution/spans, HTTP ingest, dedup, trace inspector. Acceptance: one mock request yields inspectable linked spans in DB.

**Milestone D — policies/approval:** code-owned revisions, hash registration, submit/approve, action-bound grants, deny/bypass tests. Acceptance: unauthorized rollback refused and evidence linked; reviewer can't approve self-authored revision.

**Milestone E — build eval:** deterministic eval runner and stored test artifacts, gate, failing build workflow. Acceptance: unsafe test blocks release, safe build with approval eligible.

**Milestone F — metrics/incidents:** model/tool orchestration latency and cost provenance, heartbeat, severity and evidence export. Acceptance: widgets computed from database; absent telemetry shows Unknown.

**Milestone G — Keewano:** explicit opt-in credentials, typed event registration/ingest, history backfill, actual MCP query, query result changes advisory recommendation, graceful disabled/failure behavior. Acceptance: live query demonstrably changes recommendation; runtime policy still controls execution.

**Milestone H — demo QA:** deterministic reset, end-to-end walkthrough, role/tenant negative tests, error injection, no external side effects, docs updated.

## 12. Acceptance tests / definition of done

- `docker compose ps`: exactly **one application service**; `docker ps` one R2M container; `ss -lnt` only port 3000 exposed to host.
- Frontend routes both R2M and mock agent UI without CORS workaround; API private behind reverse proxy.
- Aiven certificate is verified; no credentials in response body, images or repo.
- Every org-scoped endpoint has positive and negative RBAC test, including evidence exports and trace fetch by ID.
- SDK works as independent installable package and emits nested spans with idempotent ingestion.
- Policy stored in agent code; changing version/hash requires re-approval, and stale approval cannot authorize a new version.
- Rollback without a valid one-time action grant is denied; subsequent tool execution verifiably linked to action grant and policy decision.
- `safe` evaluation passes and `faulty` evaluation fails; failing build cannot be promoted.
- Trace evidence shows model, tool, orchestration, memory, simulated infra, decision, cost and latency where applicable; missing telemetry is Unknown.
- Vendor and customer views differ through **backend** access scopes, not merely frontend visibility.
- Keewano enabled: typed historical+live events, real MCP query, and traceable recommendation difference. Disabled: clean fallback, no false integration claims.
- Demo reset is safe, repeatable, isolated to synthetic records; no real cloud changes.

## 13. Explicit non-goals

No real production rollback, real LLM API, multi-tenant SaaS hosting, billing/subscription checkout, advanced SOC controls, hardware AI, automatic production agent patching, enterprise SSO, massive time-series retention, full cloud cost reconciliation, regulatory attestation, or distributed scaling in this prototype.

## 14. Reference

Keewano SpeedHacks Quickstart: https://docs.keewano.com/getting-started/speedhacks-quickstart (reviewed 2026-10-11). Exact MCP protocol/tool descriptions must be discovered and tested against current live service during implementation.
