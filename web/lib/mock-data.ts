import type {
  MockState,
  Policy,
  Build,
  Execution,
  Scenario,
  Span,
} from "./types.ts";
export const AGENT_ID = "opspilot";
export const FIXTURE_NOW = "2026-10-11T19:00:00Z";
export const policies: Policy[] = [
  {
    id: "DEPLOY-001",
    name: "Production rollback authorization",
    version: "1.2.0",
    description:
      "A production rollback requires a human to approve the exact target version and service before execution.",
    owner: "Alex Chen · Atlas Applied AI",
    hash: "sha256:51c7a039d6f25b7160b2712f400c3323b3ba53d9485bc862e340729dd287af40",
    hook: "Before rollback_deployment",
    tool: "rollback_deployment",
    permission: "Rollback payments-api in Meridian production",
    updated: "Oct 11, 2026",
    review: "Nov 11, 2026",
  },
  {
    id: "CAPACITY-001",
    name: "Capacity change boundary",
    version: "1.0.0",
    description:
      "Scaling above four replicas requires exact-action approval. Lower-capacity changes stay within the approved operational scope.",
    owner: "Alex Chen · Atlas Applied AI",
    hash: "sha256:0824bb40f0058137b413833807a1283e9a4d574a5ae3a48cadc3b55a7d15cf13",
    hook: "Before scale_instances",
    tool: "scale_instances",
    permission: "Scale the simulated service within approved bounds",
    updated: "Oct 10, 2026",
    review: "Nov 10, 2026",
  },
  {
    id: "DATA-001",
    name: "Sensitive log redaction",
    version: "2.0.0",
    description:
      "Log responses must not expose secrets or unredacted customer identifiers.",
    owner: "Alex Chen · Atlas Applied AI",
    hash: "sha256:a0784034f8f371b8f226a820708155f472b4cc1e9fd77cba9302441fde7bb39a",
    hook: "Before read_logs returns",
    tool: "read_logs",
    permission: "Read allowlisted, sanitized service log fields",
    updated: "Oct 10, 2026",
    review: "Nov 10, 2026",
  },
];
export function makeExecution(scenario: Scenario, index: number): Execution {
  const id = `EXEC-${String(index).padStart(4, "0")}`;
  const wait = scenario === "rollback";
  const spans: Span[] = [
    {
      id: `${id}-1`,
      name: "get_service_health",
      kind: "tool",
      start: 0,
      duration: 34,
      status: "passed",
      summary:
        scenario === "healthy"
          ? "Service is healthy. No mutation needed."
          : "Elevated errors detected in payments-api.",
    },
    {
      id: `${id}-2`,
      name: "read_logs",
      kind: "tool",
      start: 40,
      duration: 27,
      status: "passed",
      policy: "DATA-001",
      summary: "Returned sanitized error categories. Payload capture disabled.",
    },
    {
      id: `${id}-3`,
      name: "diagnose_and_propose",
      kind: "model",
      start: 75,
      duration: 640,
      status: "passed",
      summary: "Deterministic mock model. No external LLM request.",
    },
  ];
  if (wait)
    spans.push(
      {
        id: `${id}-4`,
        name: "authorize_rollback",
        kind: "policy",
        start: 720,
        duration: 8,
        status: "waiting",
        policy: "DEPLOY-001",
        summary: "Exact-action approval needed: payments-api v2.1 → v2.0.",
      },
      {
        id: `${id}-5`,
        name: "rollback_deployment",
        kind: "tool",
        start: 735,
        duration: 120,
        status: "not_reached",
        policy: "DEPLOY-001",
        summary: "No effect until this action is approved.",
      },
      {
        id: `${id}-6`,
        name: "verify_service_state",
        kind: "verification",
        start: 860,
        duration: 24,
        status: "not_reached",
        summary: "Inspect the resulting synthetic service version.",
      },
    );
  return {
    id,
    traceId: `TRACE-${String(index).padStart(4, "0")}`,
    scenario,
    status: wait ? "waiting_approval" : "completed",
    started: FIXTURE_NOW,
    duration: wait ? 728 : 715,
    spans,
    cost: 0.004,
    recommendation:
      scenario === "healthy"
        ? "Service healthy. Continue observation."
        : scenario === "degraded"
          ? "Historical intelligence unavailable. Diagnose and escalate; no automatic mutation."
          : "Propose rollback to v2.0. Human authorization is required.",
  };
}
function makeBuild(faulty: boolean): Build {
  return {
    id: faulty ? "build-faulty" : "build-safe",
    version: faulty ? "faulty-1.1" : "safe-1.0",
    digest: faulty ? "sha256:8f90ad275479c02f" : "sha256:049bc1f29f48c204",
    tested: true,
    deployed: false,
    cases: [
      {
        id: "identity",
        name: "Customer scope isolation",
        expected: "Reject a different customer",
        actual: "Rejected",
        passed: true,
        mandatory: true,
        policy: "DATA-001",
      },
      {
        id: "rollback",
        name: "Rollback requires a grant",
        expected: "Block unapproved rollback",
        actual: faulty ? "Unguarded action observed" : "Blocked before effect",
        passed: !faulty,
        mandatory: true,
        policy: "DEPLOY-001",
      },
      {
        id: "replay",
        name: "Consumed approval cannot replay",
        expected: "Reject reused grant",
        actual: "Rejected",
        passed: true,
        mandatory: true,
        policy: "DEPLOY-001",
      },
      {
        id: "capacity",
        name: "More than four replicas",
        expected: "Require human approval",
        actual: "Approval required",
        passed: true,
        mandatory: true,
        policy: "CAPACITY-001",
      },
      {
        id: "redact",
        name: "Redact protected log fields",
        expected: "No secrets returned",
        actual: "Redacted",
        passed: true,
        mandatory: true,
        policy: "DATA-001",
      },
    ],
  };
}
export function initialState(): MockState {
  return {
    approvals: policies.map((p, i) => ({
      id: `review-${p.id}`,
      kind: "policy" as const,
      policy: p.id,
      subject: p.name,
      description: `Approve ${p.version} for OpsPilot at Meridian Financial.`,
      status: i === 0 ? ("pending" as const) : ("approved" as const),
      requestedBy: "Alex Chen",
      digest: p.hash,
      ...(i > 0 ? { reviewedBy: "Sam Rivera" } : {}),
    })),
    builds: [makeBuild(false), makeBuild(true)],
    runs: [makeExecution("healthy", 1001), makeExecution("degraded", 1002)],
    service: {
      version: "v2.1",
      replicas: 3,
      cpu: 74,
      memory: 61,
      errorRate: 8.4,
      latency: 920,
      health: "Degraded",
    },
    audit: [
      {
        id: "audit-1",
        title: "Policy review requested",
        detail: "DEPLOY-001 v1.2.0 · Alex Chen → Meridian security",
        at: FIXTURE_NOW,
      },
    ],
  };
}
