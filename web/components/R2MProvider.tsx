"use client";
// Live data for every screen. The Control Plane reads/writes the R2M platform with the user's signed session; the
// Operations Desk talks to the separate OpsPilot agent service, which has its own sign-in backed by R2M accounts.
// Who you are and what you may do comes from the server (/me), never from a picker in the browser.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, request, type Session } from "@/lib/api";
import { type Command } from "@/lib/release";
import {
  APP,
  deskApprovals,
  deskRequest,
  emptyState,
  loadControl,
  mapService,
  replyToExecution,
  toLiveScenario,
} from "@/lib/live-adapter";
import type { ComponentInfo, Execution, AppState, Organization, Policy, Role, Scenario } from "@/lib/types";

// When an account holds several roles, the most privileged reviewer/release role wins the view.
const ROLE_ORDER: Role[] = ["customer_security", "customer_ops", "vendor_release_manager", "vendor_developer"];
const ORG_OF: Record<Role, Organization> = {
  vendor_developer: "atlas",
  vendor_release_manager: "atlas",
  customer_security: "meridian",
  customer_ops: "meridian",
};

interface Context {
  state: AppState;
  role: Role;
  org: Organization;
  user: { name: string; email: string; organization: string } | null;
  signOut: () => void;
  dispatch: (command: Command) => boolean;
  notify: (message: string) => void;
  reset: (scenario?: Scenario) => void;
  policies: Policy[];
  components: ComponentInfo[];
  agentId: string;
  loading: boolean;
  refresh: () => Promise<void>;
}
const R2MContext = createContext<Context | null>(null);
const errorText = (e: unknown) =>
  e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Request failed.";
const unauthorized = (e: unknown) => e instanceof ApiError && e.status === 401;
const toLogin = () =>
  window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
const onLogin = () => typeof window !== "undefined" && window.location.pathname === "/login";

export function R2MProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState>(emptyState);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [components, setComponents] = useState<ComponentInfo[]>([]);
  const [agentId, setAgentId] = useState("");
  const [installationId, setInstallationId] = useState("");
  const [role, updateRole] = useState<Role>(APP === "desk" ? "customer_ops" : "vendor_developer");
  const [user, setUser] = useState<Context["user"]>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const deskRuns = useRef<Execution[]>([]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      if (APP === "desk") {
        const s = await deskRequest("/state");
        const runs = deskRuns.current;
        setState({ ...emptyState(), service: mapService(s.service), runs,
                   approvals: deskApprovals(runs),
                   builds: [{ id: "live", version: "deployed", digest: "", tested: true, deployed: true, cases: [] }] });
      } else {
        const live = await loadControl();
        setState(live.state);
        setPolicies(live.policies);
        setComponents(live.components);
        setAgentId(live.agentId);
        setInstallationId(live.installationId);
      }
    } catch (e) {
      if (unauthorized(e)) return toLogin();
      setMessage(`Live data unavailable: ${errorText(e)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (onLogin()) return setLoading(false);
    void (async () => {
      try {
        if (APP === "control") {
          const me: Session = await api.me();
          const roles = me.organizations.flatMap((o) => o.roles);
          const r = ROLE_ORDER.find((x) => roles.includes(x));
          if (!r) throw Error("This account has no role in the R2M Control Plane.");
          updateRole(r);
          const org = me.organizations.find((o) => o.roles.includes(r));
          setUser({ name: me.user.display_name, email: me.user.email, organization: org?.name ?? "" });
        } else {
          const me = await deskRequest<{ name: string; email: string; organization: string; role: Role }>("/me");
          updateRole(me.role);
          setUser({ name: me.name, email: me.email, organization: me.organization });
        }
      } catch (e) {
        if (unauthorized(e)) return toLogin();
        setMessage(errorText(e));
        return setLoading(false);
      }
      await refresh();
    })();
  }, [refresh]);

  async function signOut() {
    try {
      if (APP === "desk") await deskRequest("/session", { method: "DELETE" });
      else await api.signOut();
    } finally {
      window.location.assign("/login");
    }
  }

  async function run(command: Command) {
    switch (command.type) {
      case "review":
        await api.decision(command.id, command.decision === "approved" ? "approve" : "reject", command.reason);
        setMessage(`Decision recorded in R2M: ${command.decision}.`);
        break;
      case "revoke":
        await api.decision(command.id, "revoke", command.reason);
        setMessage("Policy approval revoked. The next governed action is denied until it is re-approved.");
        break;
      case "evaluate":
        setMessage("Build evaluations run in CI (scripts/run_evals.py) and upload here; showing the latest results.");
        break;
      case "evaluateRelease": {
        const b = state.builds.find((x) => x.id === command.id);
        if (!b) throw Error("Unknown build.");
        const gate = await request<{ status: string }>(`/agents/${agentId}/releases/evaluate`, {
          method: "POST",
          body: JSON.stringify({ installation_id: installationId, build_version: b.version, artifact_digest: b.digest }),
        });
        setMessage(`Release gate: ${gate.status}.`);
        break;
      }
      case "deploy": {
        const b = state.builds.find((x) => x.id === command.id);
        if (!b?.deploymentId) throw Error("Evaluate the release first.");
        await api.deploy(agentId, b.deploymentId);
        setMessage(`${b.version} deployed.`);
        break;
      }
      case "run": {
        if (APP !== "desk") throw Error("Chat with OpsPilot in the Operations Desk app.");
        setMessage("OpsPilot is working (live model + R2M policy gate)…");
        const prompt = command.prompt || "How is payments-api doing?";
        const reply = await deskRequest("/message", {
          method: "POST",
          body: JSON.stringify({ message: prompt, scenario: toLiveScenario(command.scenario) }),
        });
        deskRuns.current = [replyToExecution(prompt, command.scenario, reply), ...deskRuns.current];
        setMessage(reply.decision ? `R2M decision: ${reply.decision}` : "Reply received.");
        break;
      }
    }
    await refresh();
  }

  function dispatch(command: Command) {
    void run(command).catch((e) => (unauthorized(e) ? toLogin() : setMessage(errorText(e))));
    return true;
  }

  async function doReset(scenario: Scenario = "degraded") {
    if (APP === "desk") {
      await deskRequest(`/scenarios/${toLiveScenario(scenario)}/reset`, { method: "POST" });
      deskRuns.current = [];
    } else {
      await api.resetScenario(toLiveScenario(scenario));
    }
    setMessage(`Scenario reset: ${scenario}.`);
    await refresh();
  }

  return (
    <R2MContext.Provider
      value={{
        state,
        role,
        org: ORG_OF[role],
        user,
        signOut: () => void signOut(),
        dispatch,
        notify: setMessage,
        reset: (scenario) => void doReset(scenario).catch((e) => setMessage(errorText(e))),
        policies,
        components,
        agentId,
        loading,
        refresh,
      }}
    >
      {children}
      {message && (
        <div className="toast" role="status">
          <span>{message}</span>
          <button aria-label="Dismiss notification" onClick={() => setMessage("")}>
            ×
          </button>
        </div>
      )}
    </R2MContext.Provider>
  );
}
export function useR2M() {
  const value = useContext(R2MContext);
  if (!value) throw Error("R2MProvider is required");
  return value;
}
