import test from "node:test";
import assert from "node:assert/strict";
import { modeLabel, metric, insightLabel } from "../lib/live-types.ts";
import { api } from "../lib/api.ts";
test("mode and missing metrics never imply live or healthy", () => {
  assert.equal(
    modeLabel({ mode: "simulated-fallback", model: "gpt-4o-mini" }),
    "Fallback",
  );
  assert.equal(modeLabel({ mode: "simulated" }), "Deterministic");
  assert.equal(
    modeLabel({ mode: "live", model: "gpt-4o-mini" }),
    "Live · gpt-4o-mini",
  );
  assert.equal(modeLabel({}), "Mode unknown");
  assert.equal(metric(null, "%"), "Unknown");
  assert.equal(metric(0, "%"), "0%");
  assert.equal(insightLabel(null), "Not consulted this turn");
  assert.equal(
    insightLabel({
      provider: "keewano",
      status: "ok",
      supported: false,
      sample_count: 2,
    }),
    "Insufficient history (n=2)",
  );
});
test("chat sends actual text and backend scenario with installation scope; no retry on network error", async () => {
  const original = globalThis.fetch;
  let count = 0;
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    count++;
    assert.equal(
      input,
      "/api/v1/demo/agent/message?installation_id=installation-1",
    );
    assert.deepEqual(JSON.parse(String(init?.body)), {
      message: "Scale to five replicas",
      scenario: "faulty",
    });
    assert.equal(new Headers(init?.headers).get("X-R2M-CSRF"), "1");
    throw new TypeError("Network lost");
  }) as typeof fetch;
  try {
    await assert.rejects(
      api.message("Scale to five replicas", "faulty", "installation-1"),
    );
    assert.equal(count, 1);
  } finally {
    globalThis.fetch = original;
  }
});
test("scenario selection resets only the selected backend installation", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    assert.equal(
      input,
      "/api/v1/demo/agent/scenarios/approval/reset?installation_id=installation-1",
    );
    assert.equal(init?.method, "POST");
    return new Response("{}");
  }) as typeof fetch;
  try {
    await api.resetScenario("approval", "installation-1");
  } finally {
    globalThis.fetch = original;
  }
});
