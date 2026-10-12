import type { AppState, Scenario } from "./types.ts";
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
  | { type: "revoke"; id: string; reason: string }
  | { type: "run"; scenario: Scenario; prompt?: string };
/** Release-gate checks for a build: the platform's computed gate when it has one, else derived from its eval cases. */
export function releaseChecks(state: AppState, buildId: string) {
  const b = state.builds.find((x) => x.id === buildId);
  if (b?.gate) return b.gate;
  return {
    evaluations: !!b?.tested && b.cases.every((x) => !x.mandatory || x.passed),
    policies: state.approvals
      .filter((x) => x.kind === "policy")
      .every((x) => x.status === "approved"),
    artifact: !!b,
    scope: true,
  };
}
