import type { ApiErrorBody } from "./types";
export class ApiError extends Error {
  public status: number;
  public body: ApiErrorBody;
  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status;
    this.body = body;
  }
}
export async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const raw = await response.json().catch(() => ({}));
    throw new ApiError(response.status, {
      code: typeof raw.code === "string" ? raw.code : "http_error",
      message:
        response.status === 404
          ? "Not found."
          : raw.code === "agent_unavailable"
            ? "OpsPilot is unavailable until the AI agent package is installed."
            : typeof raw.message === "string"
              ? raw.message
              : "The API request could not be completed.",
      request_id: raw.request_id || response.headers.get("x-request-id") || "",
    });
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export async function request<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//"))
    throw Error("Use an API-relative path.");
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  headers.set("X-Request-ID", crypto.randomUUID());
  return parseResponse<T>(
    await fetch(`/api/v1${path}`, {
      ...init,
      headers,
      credentials: "same-origin",
      cache: "no-store",
    }),
  );
}
export interface Identity {
  email: string;
  display_name: string;
  organization: string;
  organization_kind: string;
  role: string;
}
export interface Session {
  user: { id: string; email: string; display_name: string };
  organizations: {
    id: string;
    name: string;
    kind: string;
    slug: string;
    roles: string[];
    permissions: string[];
  }[];
  demo_auth: boolean;
}
const id = encodeURIComponent;
const post = <T = unknown>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
// Unknown response bodies are intentional until each screen has a validated DTO adapter.
// Never cast backend payloads to the local mock view models.
export const api = {
  identities: () =>
    request<{ identities: Identity[]; notice: string }>("/demo/identities"),
  signIn: (email: string) => post("/demo/session", { email }),
  signOut: () => request("/demo/session", { method: "DELETE" }),
  me: () => request<Session>("/me"),
  organizations: () => request("/organizations"),
  overview: (org: string, range = "24h") =>
    request(`/organizations/${id(org)}/overview?range=${id(range)}`),
  topology: (agent: string) => request(`/agents/${id(agent)}/topology`),
  policies: (agent: string) => request(`/agents/${id(agent)}/policies`),
  submitPolicy: (agent: string, revision: string, installation_id: string) =>
    post(`/agents/${id(agent)}/policies/${id(revision)}/submit`, {
      installation_id,
    }),
  approvals: () => request("/approvals"),
  decision: (
    approval: string,
    decision: "approve" | "reject" | "revoke",
    reason: string,
  ) => post(`/approvals/${id(approval)}/decision`, { decision, reason }),
  evaluations: (agent: string) => request(`/agents/${id(agent)}/evaluations`),
  deployments: (agent: string) => request(`/agents/${id(agent)}/deployments`),
  evaluateRelease: (
    agent: string,
    input: {
      installation_id: string;
      build_version: string;
      artifact_digest: string;
    },
  ) => post(`/agents/${id(agent)}/releases/evaluate`, input),
  deploy: (agent: string, deployment: string) =>
    post(`/agents/${id(agent)}/deployments/${id(deployment)}/deploy`),
  traces: (agent: string, cursor?: string) =>
    request(
      `/agents/${id(agent)}/traces${cursor ? `?cursor=${id(cursor)}` : ""}`,
    ),
  trace: (trace: string) => request(`/traces/${id(trace)}`),
  metrics: (agent: string, range = "24h") =>
    request(`/agents/${id(agent)}/metrics?range=${id(range)}`),
  incidents: (agent: string) => request(`/agents/${id(agent)}/incidents`),
  evidence: (agent: string) => request(`/agents/${id(agent)}/evidence`),
  exportEvidence: (agent: string) =>
    request(`/agents/${id(agent)}/evidence/export`),
  integration: () => request("/integrations/keewano"),
  configureIntegration: (organization_id: string, enabled: boolean) =>
    request("/integrations/keewano", {
      method: "PUT",
      body: JSON.stringify({ organization_id, enabled }),
    }),
  queryIntegration: (installation_id: string, question: string) =>
    post("/integrations/keewano/query", { installation_id, question }),
  agentState: () => request("/demo/agent/state"),
  message: (
    message: string,
    scenario: "healthy" | "degraded" | "approval",
    installation?: string,
  ) =>
    post(
      `/demo/agent/message${installation ? `?installation_id=${id(installation)}` : ""}`,
      { message, scenario },
    ),
  resetScenario: (scenario: string) =>
    post(`/demo/agent/scenarios/${id(scenario)}/reset`),
};
