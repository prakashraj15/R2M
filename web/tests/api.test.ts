import test from "node:test";
import assert from "node:assert/strict";
import { api, ApiError, parseResponse } from "../lib/api.ts";
test("browser session request uses relative proxy path and cookie credentials", async () => {
  const original = globalThis.fetch;
  let url: unknown;
  let options: RequestInit | undefined;
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    url = input;
    options = init;
    return new Response(JSON.stringify({ ok: true }));
  }) as typeof fetch;
  try {
    await api.signIn("dev@atlas.demo");
    assert.equal(url, "/api/v1/demo/session");
    assert.equal(options?.credentials, "same-origin");
    assert.equal(options?.cache, "no-store");
    assert.equal(options?.body, JSON.stringify({ email: "dev@atlas.demo" }));
  } finally {
    globalThis.fetch = original;
  }
});
test("404 remains not found and agent_unavailable remains a failure", async () => {
  await assert.rejects(
    parseResponse(
      new Response(
        JSON.stringify({ code: "not_found", message: "private detail" }),
        { status: 404 },
      ),
    ),
    (e: unknown) => e instanceof ApiError && e.message === "Not found.",
  );
  await assert.rejects(
    parseResponse(
      new Response(JSON.stringify({ code: "agent_unavailable" }), {
        status: 503,
      }),
    ),
    (e: unknown) =>
      e instanceof ApiError &&
      e.status === 503 &&
      e.message.includes("AI agent package"),
  );
  assert.equal(
    await parseResponse(new Response(null, { status: 204 })),
    undefined,
  );
});
