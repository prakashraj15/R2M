export type LiveScenario = "healthy" | "degraded" | "approval" | "faulty";
export interface LiveService {
  service_key: string;
  deployment_version: string;
  previous_version: string;
  replicas: number | null;
  cpu_pct: number | null;
  memory_pct: number | null;
  error_rate_pct: number | null;
  p95_latency_ms: number | null;
  health_status: string | null;
}
export interface LiveApproval {
  id: string;
  kind?: "policy" | "runtime_action";
  status: string;
  expires_at?: string;
  tool_key?: string;
  arguments?: Record<string, unknown>;
  arguments_hash?: string;
  trace_id?: string;
  execution_id?: string;
  agent_id?: string;
  installation_id?: string;
  customer_org_id?: string;
  can_decide?: boolean;
  policy_key?: string;
  version?: string;
  description?: string;
}
export interface DemoState {
  installation_id: string;
  agent_id: string;
  customer_org_id: string;
  services: LiveService[];
  scenarios: LiveScenario[];
  approvals: LiveApproval[];
  recent_actions: {
    kind: string;
    authorized: boolean;
    created_at: string;
    tool_action_id: string | null;
  }[];
  last_execution: { id: string; trace_id: string; status: string } | null;
  notice: string;
}
export interface Insight {
  provider: string;
  status: string;
  supported?: boolean;
  sample_count?: number | null;
  label?: string;
  candidates?: { remediation: string; samples: number; successes: number }[];
}
export interface AgentReply {
  reply: string;
  mode?: string;
  model?: string;
  scenario?: LiveScenario;
  decision: string | null;
  reasons?: string[];
  steps?: string[];
  proposal?: {
    tool: string;
    arguments: Record<string, unknown>;
    rationale?: string;
    source: string;
  } | null;
  insight?: Insight | null;
  build?: { version: string; deployment_status: string };
  suggestions?: string[];
  cost_label?: string;
  verified?: boolean;
  service_before?: LiveService;
  service_after?: LiveService;
  trace_id?: string;
  execution_id?: string;
  approval_id?: string;
  action_id?: string;
}
export interface Topology {
  nodes: {
    id: string;
    component_key: string;
    label: string;
    kind: string;
    status: string | null;
    source: string;
    metrics: {
      calls: number | null;
      errors: number | null;
      p95_ms: number | null;
      cost_usd: number | null;
    } | null;
  }[];
  edges: {
    id: string;
    source_component_id: string;
    target_component_id: string;
  }[];
}
export interface Integration {
  platform_enabled: boolean;
  adapter_installed: boolean;
  organizations: {
    organization_id: string;
    name: string;
    enabled: boolean;
    backlog: number;
    dead: number;
  }[];
}
export const scenarioTitles: Record<LiveScenario, string> = {
  healthy: "Healthy observation",
  degraded: "Degraded payments-api",
  approval: "Approval-required rollback",
  faulty: "Faulty build (fault injection)",
};
export function modeLabel(reply: Pick<AgentReply, "mode" | "model">) {
  return reply.mode === "live"
    ? `Live · ${reply.model || "model unspecified"}`
    : reply.mode === "simulated"
      ? "Deterministic"
      : reply.mode === "simulated-fallback"
        ? "Fallback"
        : "Mode unknown";
}
export function metric(value: number | null | undefined, unit = "") {
  return value == null ? "Unknown" : `${value}${unit}`;
}
export function insightLabel(insight: Insight | null | undefined) {
  if (!insight) return "Not consulted this turn";
  if (insight.status === "unavailable") return "Intelligence unavailable";
  if (insight.status === "failed") return "Intelligence query failed";
  if (insight.status === "ok" && !insight.supported)
    return `Insufficient history (n=${insight.sample_count ?? "Unknown"})`;
  return insight.label || "History returned";
}
