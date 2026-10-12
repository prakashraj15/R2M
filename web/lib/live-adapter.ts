// Maps live R2M / OpsPilot API responses onto the view models the original screens render.
// Control Plane data comes from the R2M platform (/api/v1, signed session cookie);
// Operations Desk data comes from the OpsPilot agent service (/agent-api).
import { ApiError, request } from "./api";
import type {
  Approval,
  Build,
  ComponentInfo,
  Execution,
  Health,
  AppState,
  Policy,
  Scenario,
  ServiceState,
  Span,
  SpanStatus,
  TestCase,
} from "./types";

type Obj = Record<string, any>;

export const APP: "control" | "desk" =
  process.env.NEXT_PUBLIC_R2M_APP === "desk" ? "desk" : "control";
export const CONTROL_URL = (process.env.NEXT_PUBLIC_CONTROL_URL || "http://localhost:3000").replace(/\/$/, "");
export const DESK_URL = (process.env.NEXT_PUBLIC_DESK_URL || "http://localhost:3001").replace(/\/$/, "");
/** A Control Plane path, absolute when rendered inside the Operations Desk app. */
export const cp = (path: string) => (APP === "desk" ? `${CONTROL_URL}${path}` : path);

export const emptyState = (): AppState => ({
  approvals: [],
  builds: [],
  runs: [],
  service: { version: "Unknown", replicas: 0, cpu: 0, memory: 0, errorRate: 0, latency: 0, health: "Unknown" },
  audit: [],
});

const health = (h?: string | null): Health =>
  h === "healthy" ? "Healthy" : h === "degraded" ? "Degraded" : h === "critical" ? "Critical" : "Unknown";

export const toLiveScenario = (s: Scenario | string) => (s === "rollback" ? "approval" : s);

export function mapService(s: Obj | undefined): ServiceState {
  if (!s) return emptyState().service;
  return {
    version: s.deployment_version,
    replicas: s.replicas,
    cpu: Math.round(s.cpu_pct),
    memory: Math.round(s.memory_pct),
    errorRate: s.error_rate_pct,
    latency: Math.round(s.p95_latency_ms),
    health: health(s.health_status),
  };
}

const spanStatus = (status?: string): SpanStatus =>
  status === "error" || status === "failed"
    ? "failed"
    : status === "denied"
      ? "blocked"
      : status === "pending_approval" || status === "running"
        ? "waiting"
        : status === "placeholder"
          ? "not_reached"
          : "passed";

// ---------------------------------------------------------------- Control Plane
export async function loadControl(): Promise<{
  agentId: string;
  installationId: string;
  state: AppState;
  policies: Policy[];
  components: ComponentInfo[];
}> {
  const [ops, approvals] = await Promise.all([
    request<Obj>("/operations/state"),
    request<Obj>("/approvals"),
  ]);
  const agent = ops.agent_id as string;
  const inst = ops.installation_id as string;
  const q = `installation_id=${inst}`;
  const [pol, deps, evals, traces, topo, evidence] = await Promise.all([
    request<Obj>(`/agents/${agent}/policies?${q}`),
    request<Obj>(`/agents/${agent}/deployments?${q}`),
    request<Obj>(`/agents/${agent}/evaluations`),
    request<Obj>(`/agents/${agent}/traces?${q}&limit=8`),
    request<Obj>(`/agents/${agent}/topology?${q}`),
    request<Obj>(`/agents/${agent}/evidence?${q}&limit=20`),
  ]);
  const details = await Promise.all(
    (traces.traces as Obj[]).map((t) => request<Obj>(`/traces/${t.trace_id}`).catch(() => null)),
  );

  const policies: Policy[] = (pol.policies as Obj[]).map((p) => {
    const active = (p.submissions as Obj[]).find((s) => s.active);
    const pending = (p.submissions as Obj[]).find((s) => s.status === "pending");
    return {
      id: p.policy_key,
      name: p.description,
      version: p.version,
      description: p.description,
      owner: p.owner_email || "Atlas Applied AI",
      hash: p.artifact_hash,
      hook: p.definition_metadata?.scope ? `${p.enforcement_point} · ${p.definition_metadata.scope}` : p.enforcement_point,
      tool: (p.definition_metadata?.tools || []).join(", "),
      permission: active ? "Approved" : pending ? "Pending approval" : "Not approved",
      updated: String(p.created_at).slice(0, 10),
      review: active ? "Active" : "—",
    };
  });
  const allPoliciesActive =
    pol.policies.length > 0 && (pol.policies as Obj[]).every((p) => (p.submissions as Obj[]).some((s) => s.active));

  const runsByBuild = new Map<string, Obj[]>();
  for (const r of evals.runs as Obj[]) runsByBuild.set(r.build_id, [...(runsByBuild.get(r.build_id) || []), r]);
  const seen = new Set<string>();
  const builds: Build[] = [];
  for (const d of deps.deployments as Obj[]) {
    if (seen.has(d.build_id)) continue;
    seen.add(d.build_id);
    const runs = runsByBuild.get(d.build_id) || [];
    const latestBySuite = new Map<string, Obj>();
    for (const r of runs) if (!latestBySuite.has(r.suite_key)) latestBySuite.set(r.suite_key, r);
    const cases: TestCase[] = [...latestBySuite.values()].flatMap((r) =>
      (r.cases as Obj[]).map((c) => ({
        id: c.id,
        name: `${r.suite_key} · ${c.case_key}`,
        expected: JSON.stringify(c.expected),
        actual: JSON.stringify(c.actual),
        passed: c.status === "passed",
        mandatory: c.mandatory,
        policy: "",
      })),
    );
    const tested = cases.length > 0;
    builds.push({
      id: d.build_id,
      version: d.version,
      digest: d.artifact_digest,
      tested,
      deployed: d.status === "deployed",
      releaseEvaluated: ["eligible", "blocked", "deployed"].includes(d.status),
      cases,
      deploymentId: d.id,
      deploymentStatus: d.status,
      gate: {
        evaluations: tested && cases.every((c) => !c.mandatory || c.passed),
        policies: allPoliciesActive,
        artifact: true,
        scope: true,
      },
    });
  }

  const mapped: Approval[] = (approvals.approvals as Obj[]).map((a) =>
    a.kind === "policy"
      ? {
          id: a.id,
          kind: "policy",
          policy: a.policy_key,
          subject: `${a.policy_key} ${a.version}`,
          description: a.description,
          status: a.status === "approved" ? "approved" : a.status === "pending" ? "pending" : "rejected",
          requestedBy: a.submitted_by_email,
          digest: a.artifact_hash,
        }
      : {
          id: a.id,
          kind: "action",
          policy: a.reason_code || "runtime approval",
          subject: `${a.tool_key} ${JSON.stringify(a.arguments)}`,
          description: `${a.reason_code || "Exact-action approval"} · ${a.agent_name}`,
          status: ["approved", "consumed"].includes(a.status) ? "approved" : a.status === "pending" ? "pending" : "rejected",
          requestedBy: "OpsPilot",
          digest: a.arguments_hash,
          executionId: a.trace_id,
        },
  );

  const runs: Execution[] = details.filter(Boolean).map((t) => traceToExecution(t as Obj));
  const components = groupTopology(topo.nodes as Obj[], (ops.services as Obj[])[0]);
  const state: AppState = {
    approvals: mapped,
    builds,
    runs,
    service: mapService((ops.services as Obj[])[0]),
    audit: (evidence.items as Obj[]).map((e) => ({
      id: e.id,
      title: e.evidence_type.replaceAll("_", " "),
      detail: `${e.integrity_ok ? "Integrity verified" : "Integrity mismatch"} · sha256 ${String(e.sha256).slice(0, 12)}…`,
      at: e.created_at,
    })),
  };
  return { agentId: agent, installationId: inst, state, policies, components };
}

// The original canvas has six architecture nodes; live components (several tools, memory, database…) are grouped
// into them with summed calls/errors, the worst p95 and the worst health. Missing telemetry stays Unknown.
const GROUPS: [string, string, string, string[]][] = [
  ["orchestrator", "OpsPilot orchestrator", "orchestrator", ["orchestrator"]],
  ["model", "Agent model", "model", ["model"]],
  ["gateway", "Policy gate (R2M SDK)", "gateway", ["gateway"]],
  ["tools", "Operations tools", "tool", ["tool"]],
  ["service", "payments-api", "compute", ["compute"]],
  ["memory", "Memory & trace store", "storage", ["memory", "storage"]],
];
const RANK: Health[] = ["Healthy", "Unknown", "Degraded", "Critical"];
function groupTopology(nodes: Obj[], service: Obj | undefined): ComponentInfo[] {
  return GROUPS.map(([id, name, kind, kinds]) => {
    const members = nodes.filter((n) => kinds.includes(n.kind));
    const observed = members.filter((n) => n.metrics?.calls);
    const sum = (k: string) => (observed.length ? observed.reduce((a, n) => a + (n.metrics?.[k] || 0), 0) : null);
    const p95 = observed.map((n) => n.metrics?.p95_ms).filter((v) => v != null);
    let h: Health = members.length
      ? members.map((n) => health(n.status)).reduce((a, b) => (RANK.indexOf(b) > RANK.indexOf(a) ? b : a), "Healthy")
      : "Unknown";
    if (id === "service" && service) h = health(service.health_status);
    return {
      id,
      name,
      kind,
      description: members.length ? members.map((n) => n.label).join(", ") : "No registered component",
      health: h,
      calls: sum("calls"),
      errors: sum("errors"),
      latency: p95.length ? Math.round(Math.max(...p95)) : null,
    };
  });
}

function traceToExecution(t: Obj): Execution {
  const ex = t.execution;
  const spans = (t.spans as Obj[]).filter((s) => s.status !== "placeholder");
  const t0 = spans.length ? Math.min(...spans.map((s) => Date.parse(s.started_at))) : Date.parse(ex.started_at);
  const decisions = t.decisions as Obj[];
  const waiting = (t.approvals as Obj[]).some((a) => a.status === "pending");
  const rejected = ex.status === "failed" || decisions.some((d) => d.decision === "deny");
  const mapped: Span[] = spans.map((s) => ({
    id: s.id,
    name: s.name,
    kind: s.kind,
    start: Math.max(0, Date.parse(s.started_at) - t0),
    duration: Math.round(Number(s.duration_ms) || 0),
    status: spanStatus(s.status),
    policy: s.attributes?.policy_key || s.attributes?.decision_id ? s.attributes?.policy_key : undefined,
    summary: s.attributes?.tool ? `${s.attributes.tool} · ${s.status}` : `${s.kind} · ${s.status}`,
  }));
  const ended = ex.ended_at ? Date.parse(ex.ended_at) : NaN;
  return {
    id: String(ex.id).slice(0, 8),
    traceId: ex.trace_id,
    scenario: (ex.scenario === "approval" ? "rollback" : ex.scenario || "degraded") as Scenario,
    status: waiting ? "waiting_approval" : rejected ? "rejected" : "completed",
    started: ex.started_at,
    duration: Number.isFinite(ended) ? Math.max(0, ended - Date.parse(ex.started_at)) : 0,
    spans: mapped,
    cost: (t.usage as Obj[]).reduce((n, u) => n + Number(u.amount_usd || 0), 0),
    modelCalls: (t.usage as Obj[]).length,
    costSources: [...new Set((t.usage as Obj[]).map((u) => String(u.cost_source)))],
    recommendation: decisions.length
      ? decisions.map((d) => `${d.decision.toUpperCase()} · ${d.reason_code}`).join("; ")
      : "Observation only; no state-changing action.",
  };
}

// ---------------------------------------------------------------- Operations Desk
export async function deskRequest<T = Obj>(path: string, init?: RequestInit): Promise<T> {
  const unsafe = ["POST", "PUT", "PATCH", "DELETE"].includes((init?.method || "GET").toUpperCase());
  const r = await fetch(`/agent-api${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(unsafe ? { "X-R2M-CSRF": "1" } : {}), ...(init?.headers || {}) },
    credentials: "same-origin",
    cache: "no-store",
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, { code: String(r.status), message: body.detail || body.message || `OpsPilot request failed (${r.status})`, request_id: "" });
  return body as T;
}

/** One agent turn as a run the original chat and trace components can render. */
export function replyToExecution(prompt: string, scenario: Scenario, reply: Obj): Execution {
  const steps: string[] = [].concat(reply.steps || []);
  const decision: string | undefined = reply.decision;
  const spans: Span[] = steps.map((step, i) => ({
    id: `${reply.trace_id || "turn"}-${i}`,
    name: step.toLowerCase().replaceAll("_", " "),
    kind: "orchestration",
    start: i,
    duration: 1,
    status: step === "WAIT_APPROVAL" ? "waiting" : step === "DENIED" ? "blocked" : "passed",
    summary: step,
  }));
  return {
    id: String(reply.execution_id || reply.trace_id || Date.now()).slice(0, 8),
    traceId: reply.trace_id || "",
    scenario,
    status: decision === "REQUIRE_APPROVAL" ? "waiting_approval" : decision === "DENY" ? "rejected" : "completed",
    started: new Date().toISOString(),
    duration: 0,
    spans,
    cost: 0,
    recommendation: reply.reply || reply.message || "",
    prompt,
    decision,
    reasons: reply.reasons || [],
    proposal: reply.proposal,
    insight: reply.keewano || reply.insight,
    actionId: reply.action_id,
    approvalId: reply.approval_id,
  };
}

/** The desk's view of exact-action approvals, derived from the agent's own turns. */
export function deskApprovals(runs: Execution[]): Approval[] {
  const byAction = new Map<string, Approval>();
  for (const run of [...runs].reverse()) {
    if (!run.actionId || !run.proposal) continue;
    const prior = byAction.get(run.actionId);
    byAction.set(run.actionId, {
      id: run.approvalId || prior?.id || run.actionId,
      kind: "action",
      policy: (run.reasons || [])[0] || "runtime approval",
      subject: `${run.proposal.tool} ${JSON.stringify(run.proposal.arguments)}`,
      description: (run.reasons || []).join(", "),
      status: run.decision === "ALLOW" ? "approved" : run.decision === "DENY" ? "rejected" : "pending",
      requestedBy: "OpsPilot",
      digest: run.actionId,
      executionId: run.traceId,
    });
  }
  return [...byAction.values()].reverse();
}
