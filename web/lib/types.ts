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
export interface MockState {
  approvals: Approval[];
  builds: Build[];
  runs: Execution[];
  service: ServiceState;
  audit: AuditEvent[];
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
