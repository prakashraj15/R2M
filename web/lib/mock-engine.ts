import type { MockState, Role, Scenario } from "./types.ts";
import { canDeploy, canEvaluate, canReview, canRun } from "./permissions.ts";
import { makeExecution, FIXTURE_NOW } from "./mock-data.ts";
export type Command =
  | {
      type: "review";
      id: string;
      decision: "approved" | "rejected";
      reason: string;
    }
  | { type: "evaluate"; id: string }
  | { type: "evaluateRelease"; id: string }
  | { type: "deploy"; id: string }
  | { type: "run"; scenario: Scenario; prompt?: string };
export function releaseChecks(state: MockState, buildId: string) {
  const b = state.builds.find((x) => x.id === buildId);
  return {
    evaluations: !!b?.tested && b.cases.every((x) => !x.mandatory || x.passed),
    policies: state.approvals
      .filter((x) => x.kind === "policy")
      .every((x) => x.status === "approved"),
    artifact: !!b,
    scope: true,
  };
}
export function applyCommand(
  source: MockState,
  role: Role,
  command: Command,
): MockState {
  const state = structuredClone(source);
  const audit = (title: string, detail: string) =>
    state.audit.unshift({
      id: `audit-${state.audit.length + 1}`,
      title,
      detail,
      at: FIXTURE_NOW,
    });
  if (command.type === "review") {
    if (!canReview(role))
      throw Error(
        "Switch to Meridian Financial · Security reviewer to review requests.",
      );
    const approval = state.approvals.find((x) => x.id === command.id);
    if (!approval || approval.status !== "pending")
      throw Error("This request is no longer pending.");
    if (!command.reason.trim()) throw Error("Enter a reason for the decision.");
    if (
      approval.kind === "action" &&
      command.decision === "approved" &&
      !state.approvals.some(
        (x) =>
          x.kind === "policy" &&
          x.policy === approval.policy &&
          x.status === "approved",
      )
    )
      throw Error(
        "Approve the governing policy revision before approving this action.",
      );
    approval.status = command.decision;
    approval.reason = command.reason.trim();
    approval.reviewedBy = "Sam Rivera";
    if (approval.kind === "action") {
      const run = state.runs.find((x) => x.id === approval.executionId);
      if (!run || run.status !== "waiting_approval")
        throw Error("The execution is no longer waiting.");
      run.status = command.decision === "approved" ? "completed" : "rejected";
      run.spans = run.spans.map((s) =>
        s.kind === "policy"
          ? {
              ...s,
              status: command.decision === "approved" ? "passed" : "blocked",
              summary:
                command.decision === "approved"
                  ? "Exact-action approval consumed in simulation."
                  : "Reviewer rejected this action.",
            }
          : s.status === "not_reached" && command.decision === "approved"
            ? { ...s, status: "passed" }
            : s,
      );
      if (command.decision === "approved") {
        state.service = {
          version: "v2.0",
          replicas: 3,
          cpu: 32,
          memory: 48,
          errorRate: 0.2,
          latency: 180,
          health: "Healthy",
        };
        run.duration = 884;
        run.recommendation =
          "Approved rollback completed; synthetic state verified.";
      }
    }
    audit(
      `${approval.kind === "policy" ? "Policy" : "Action"} ${command.decision}`,
      `${approval.subject} · Sam Rivera · ${approval.reason}`,
    );
  }
  if (command.type === "evaluate") {
    if (!canEvaluate(role))
      throw Error("Only the simulated release manager can run build checks.");
    const build = state.builds.find((x) => x.id === command.id);
    if (!build) throw Error("Build not found.");
    build.tested = true;
    audit(
      "Build evaluation simulated",
      `${build.version} · ${build.cases.filter((x) => x.passed).length}/${build.cases.length} expected checks pass`,
    );
  }
  if (command.type === "evaluateRelease") {
    if (!canDeploy(role))
      throw Error("Only the release manager can evaluate release eligibility.");
    const build = state.builds.find((b) => b.id === command.id);
    if (!build) throw Error("Build not found.");
    build.releaseEvaluated = Object.values(
      releaseChecks(state, command.id),
    ).every(Boolean);
    audit(
      "Release evaluated",
      `${command.id} · ${build.releaseEvaluated ? "eligible" : "blocked"}`,
    );
  }
  if (command.type === "deploy") {
    if (!canDeploy(role))
      throw Error("Only the simulated release manager can promote a build.");
    if (!Object.values(releaseChecks(state, command.id)).every(Boolean))
      throw Error(
        "Release blocked: all mandatory tests and policy approvals are required.",
      );
    if (!state.builds.find((b) => b.id === command.id)?.releaseEvaluated)
      throw Error("Evaluate release eligibility before deployment.");
    state.builds.forEach((b) => (b.deployed = b.id === command.id));
    audit("Deployment simulated", command.id);
  }
  if (command.type === "run") {
    if (!canRun(role))
      throw Error(
        "Switch to an Atlas developer or release manager to run the demonstration.",
      );
    if (!state.builds.some((b) => b.deployed))
      throw Error(
        "Build is proposed. Evaluate and deploy the safe build before running OpsPilot.",
      );
    if (state.runs.some((x) => x.status === "waiting_approval"))
      throw Error(
        "Resolve the pending action before starting another scenario.",
      );
    const run = makeExecution(command.scenario, 1001 + state.runs.length);
    run.prompt = command.prompt;
    state.runs.unshift(run);
    state.service =
      command.scenario === "healthy"
        ? {
            version: "v2.0",
            replicas: 3,
            cpu: 32,
            memory: 48,
            errorRate: 0.2,
            latency: 180,
            health: "Healthy",
          }
        : {
            version: "v2.1",
            replicas: 3,
            cpu: 74,
            memory: 61,
            errorRate: 8.4,
            latency: 920,
            health: "Degraded",
          };
    if (command.scenario === "rollback")
      state.approvals.unshift({
        id: `action-${run.id}`,
        kind: "action",
        policy: "DEPLOY-001",
        subject: "Rollback payments-api to v2.0",
        description:
          "Meridian Financial · production simulation · current v2.1 → target v2.0",
        status: "pending",
        requestedBy: "OpsPilot / Alex Chen",
        digest: `demo-bound-${run.id}-payments-api-v2.0`,
        executionId: run.id,
      });
    audit("Agent scenario simulated", `${run.id} · ${command.scenario}`);
  }
  return state;
}
