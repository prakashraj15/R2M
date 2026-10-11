import test from "node:test";
import assert from "node:assert/strict";
import { initialState } from "../lib/mock-data.ts";
import { applyCommand, releaseChecks } from "../lib/mock-engine.ts";
test("failed mandatory check blocks promotion even with policy approval", () => {
  let s = initialState();
  s = applyCommand(s, "customer_security", {
    type: "review",
    id: "review-DEPLOY-001",
    decision: "approved",
    reason: "Reviewed scope",
  });
  assert.equal(
    Object.values(releaseChecks(s, "build-safe")).every(Boolean),
    true,
  );
  assert.throws(
    () =>
      applyCommand(s, "vendor_release_manager", {
        type: "deploy",
        id: "build-faulty",
      }),
    /Release blocked/,
  );
});
test("vendor cannot self-approve and operations viewer cannot run", () => {
  assert.throws(() =>
    applyCommand(deployedFixture(), "vendor_developer", {
      type: "review",
      id: "review-DEPLOY-001",
      decision: "approved",
      reason: "Self",
    }),
  );
  assert.throws(() =>
    applyCommand(initialState(), "customer_ops", {
      type: "run",
      scenario: "rollback",
    }),
  );
});
test("approval changes the bound run and service once; it cannot bypass policy", () => {
  let s = applyCommand(deployedFixture(), "vendor_developer", {
    type: "run",
    scenario: "rollback",
  });
  const action = s.approvals.find((a) => a.kind === "action")!;
  assert.equal(s.service.version, "v2.1");
  assert.throws(
    () =>
      applyCommand(s, "customer_security", {
        type: "review",
        id: action.id,
        decision: "approved",
        reason: "Reviewed",
      }),
    /governing policy/,
  );
  s = applyCommand(s, "customer_security", {
    type: "review",
    id: "review-DEPLOY-001",
    decision: "approved",
    reason: "Reviewed policy",
  });
  s = applyCommand(s, "customer_security", {
    type: "review",
    id: action.id,
    decision: "approved",
    reason: "Reviewed action",
  });
  assert.equal(s.service.version, "v2.0");
  assert.equal(s.runs[0].status, "completed");
  assert.ok(s.runs[0].spans.every((x) => x.status === "passed"));
  assert.throws(
    () =>
      applyCommand(s, "customer_security", {
        type: "review",
        id: action.id,
        decision: "approved",
        reason: "Replay",
      }),
    /no longer pending/,
  );
});
test("rejecting an action preserves the service version and leaves tool unexecuted", () => {
  let s = applyCommand(deployedFixture(), "vendor_developer", {
    type: "run",
    scenario: "rollback",
  });
  const action = s.approvals.find((a) => a.kind === "action")!;
  s = applyCommand(s, "customer_security", {
    type: "review",
    id: action.id,
    decision: "rejected",
    reason: "Insufficient context",
  });
  assert.equal(s.service.version, "v2.1");
  assert.equal(s.runs[0].status, "rejected");
  assert.equal(
    s.runs[0].spans.find((x) => x.name === "rollback_deployment")?.status,
    "not_reached",
  );
});

// Represents an already deployed installation for runtime-policy tests.
function deployedFixture() {
  const state = initialState();
  state.builds[0].deployed = true;
  return state;
}
test("proposed build is blocked until release is evaluated and deployed", () => {
  assert.throws(
    () =>
      applyCommand(initialState(), "vendor_developer", {
        type: "run",
        scenario: "rollback",
      }),
    /proposed/,
  );
  let state = applyCommand(initialState(), "customer_security", {
    type: "review",
    id: "review-DEPLOY-001",
    decision: "approved",
    reason: "Reviewed",
  });
  assert.throws(
    () =>
      applyCommand(state, "vendor_release_manager", {
        type: "deploy",
        id: "build-safe",
      }),
    /Evaluate release/,
  );
  state = applyCommand(state, "vendor_release_manager", {
    type: "evaluateRelease",
    id: "build-safe",
  });
  state = applyCommand(state, "vendor_release_manager", {
    type: "deploy",
    id: "build-safe",
  });
  state = applyCommand(state, "vendor_developer", {
    type: "run",
    scenario: "rollback",
  });
  assert.equal(state.runs[0].status, "waiting_approval");
});
