import test from "node:test";
import assert from "node:assert/strict";
import {
  api,
  ApiError,
  parseResponse,
  retryAfterMs,
  fetchWithRateLimit,
} from "../lib/api.ts";
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
    await api.signIn("dev@atlas.demo", "pw-for-test");
    assert.equal(url, "/api/v1/auth/session");
    assert.equal(options?.credentials, "same-origin");
    assert.equal(options?.cache, "no-store");
    assert.equal(options?.body, JSON.stringify({ email: "dev@atlas.demo", password: "pw-for-test" }));
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
      e.message.includes("agent service is unavailable"),
  );
  assert.equal(
    await parseResponse(new Response(null, { status: 204 })),
    undefined,
  );
});

test("all browser mutation methods carry CSRF, including login and logout", async () => {
  const original = globalThis.fetch;
  const calls: RequestInit[] = [];
  globalThis.fetch = (async (_input: unknown, init: RequestInit) => {
    calls.push(init);
    return new Response("{}");
  }) as typeof fetch;
  try {
    await api.signIn("dev@atlas.demo", "pw-for-test");
    await api.signOut();
    await api.configureIntegration("demo-org", true);
    await api.updateIncident("incident-1", "investigating", "Reviewing");
    await api.me();
    assert.deepEqual(
      calls.map((c) => c.method || "GET"),
      ["POST", "DELETE", "PUT", "PATCH", "GET"],
    );
    for (const call of calls.slice(0, 4))
      assert.equal(new Headers(call.headers).get("X-R2M-CSRF"), "1");
    assert.equal(new Headers(calls[4].headers).has("X-R2M-CSRF"), false);
  } finally {
    globalThis.fetch = original;
  }
});
test("rate limits retry the same mutation with headers and body preserved", async () => {
  const original = globalThis.fetch;
  const calls: RequestInit[] = [];
  globalThis.fetch = (async (_input: unknown, init: RequestInit) => {
    calls.push(init);
    return calls.length === 1
      ? new Response('{"code":"rate_limited"}', {
          status: 429,
          headers: { "Retry-After": "0" },
        })
      : new Response('{"ok":true}');
  }) as typeof fetch;
  try {
    await api.signIn("dev@atlas.demo", "pw-for-test");
    assert.equal(calls.length, 2);
    assert.equal(calls[0].body, calls[1].body);
    assert.equal(new Headers(calls[1].headers).get("X-R2M-CSRF"), "1");
  } finally {
    globalThis.fetch = original;
  }
});
test("rate retries are bounded and other failures are never retried", async () => {
  const original = globalThis.fetch;
  let count = 0;
  globalThis.fetch = (async () => {
    count++;
    return new Response('{"code":"rate_limited"}', {
      status: 429,
      headers: { "Retry-After": "0" },
    });
  }) as typeof fetch;
  try {
    await assert.rejects(
      api.me(),
      (e: unknown) => e instanceof ApiError && e.status === 429,
    );
    assert.equal(count, 4);
    count = 0;
    globalThis.fetch = (async () => {
      count++;
      return new Response('{"code":"agent_unavailable"}', { status: 503 });
    }) as typeof fetch;
    await assert.rejects(api.resetScenario("healthy"));
    assert.equal(count, 1);
  } finally {
    globalThis.fetch = original;
  }
});

test("Retry-After supports seconds, HTTP dates and missing headers", () => {
  assert.equal(retryAfterMs("2"), 2000);
  assert.equal(retryAfterMs("Thu, 01 Jan 1970 00:00:05 GMT", 1000), 4000);
  assert.equal(retryAfterMs("Thu, 01 Jan 1970 00:00:00 GMT", 1000), 0);
  assert.equal(retryAfterMs(null), 1000);
});
test("aborting during Retry-After cancels a pending retry", async () => {
  const original = globalThis.fetch;
  const controller = new AbortController();
  let calls = 0;
  globalThis.fetch = (async () => {
    calls++;
    return new Response('{"code":"rate_limited"}', {
      status: 429,
      headers: { "Retry-After": "60" },
    });
  }) as typeof fetch;
  try {
    const pending = fetchWithRateLimit("/api/v1/me", {
      signal: controller.signal,
    });
    const timer = setTimeout(() => controller.abort(), 10);
    try {
      await assert.rejects(pending, { name: "AbortError" });
    } finally {
      clearTimeout(timer);
    }
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = original;
  }
});
