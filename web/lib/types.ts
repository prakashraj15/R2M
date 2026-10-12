export type Role =
  | "vendor_developer"
  | "vendor_release_manager"
  | "customer_security"
  | "customer_ops";
export type Organization = "atlas" | "meridian";
export type Health = "Healthy" | "Degraded" | "Critical" | "Unknown";
export type Scenario = "healthy" | "degraded" | "rollback";
export type Decision = "pending" | "approved" | "rejected";
export type SpanStatus =
  | "passed"
  | "failed"
  | "waiting"
  | "blocked"
  | "not_reached";
export interface Policy {
  id: string;
  name: string;
  version: string;
  description: string;
  owner: string;
  hash: string;
  hook: string;
  tool: string;
  permission: string;
  updated: string;
  review: string;
  revisionId: string; // latest revision of this policy
  activeVersion?: string; // the revision currently approved here, when it isn't the latest
  canSubmit: boolean; // latest revision has no pending or active submission at this installation
}
export interface Span {
  id: string;
  name: string;
  kind: string;
  start: number;
  duration: number;
  status: SpanStatus;
  policy?: string;
  summary: string;
}
export interface Execution {
  id: string;
  traceId: string;
  scenario: Scenario;
  status: "completed" | "waiting_approval" | "rejected";
  started: string;
  duration: number;
  spans: Span[];
  cost: number;
  recommendation: string;
  prompt?: string;
  // Live agent turn details (Operations Desk)
  decision?: string;
  reasons?: string[];
  proposal?: { tool: string | null; arguments: Record<string, unknown>; source?: string; rationale?: string };
  insight?: { status?: string; supported?: boolean; sample_count?: number; best?: unknown; [k: string]: unknown };
  actionId?: string;
  approvalId?: string;
  modelCalls?: number;
  costSources?: string[];
}
export interface Approval {
  id: string;
  kind: "policy" | "action";
  policy: string;
  subject: string;
  description: string;
  status: Decision;
  requestedBy: string;
  digest: string;
  executionId?: string;
  reason?: string;
  reviewedBy?: string;
  canDecide?: boolean; // the server's answer for the signed-in user (role, own submission, still pending)
}
export interface TestCase {
  id: string;
  name: string;
  expected: string;
  actual: string;
  passed: boolean;
  mandatory: boolean;
  policy: string;
}
export interface Build {
  id: string;
  version: string;
  digest: string;
  tested: boolean;
  deployed: boolean;
  releaseEvaluated?: boolean;
  cases: TestCase[];
  // Live release state (Control Plane)
  deploymentId?: string;
  deploymentStatus?: string;
  gate?: { evaluations: boolean; policies: boolean; artifact: boolean; scope: boolean };
  evaluatedAt?: string; // latest CI upload
  declaredPolicies?: string[]; // the build's policy manifest (key@version)
  unapprovedPolicies?: string[]; // of those, not yet approved at this installation
  suites?: string[];
}
export interface ServiceState {
  version: string;
  replicas: number;
  cpu: number;
  memory: number;
  errorRate: number;
  latency: number;
  health: Health;
}
export interface AuditEvent {
  id: string;
  title: string;
  detail: string;
  at: string;
}
/** Who and what the screens are about, as registered in R2M (never assumed by the UI). */
export interface Identity {
  agent: string;
  agentSlug: string;
  vendor: string;
  customer: string;
  environment: string;
  service: string;
}
export interface AppState {
  approvals: Approval[];
  builds: Build[];
  runs: Execution[];
  service: ServiceState;
  audit: AuditEvent[];
  identity: Identity;
}
export interface ComponentInfo {
  id: string;
  name: string;
  kind: string;
  description: string;
  health: Health;
  calls: number | null;
  errors: number | null;
  latency: number | null;
}
export interface ApiErrorBody {
  code: string;
  message: string;
  request_id: string;
}
export interface PageResponse<T> {
  items: T[];
  next_cursor: string | null;
}
