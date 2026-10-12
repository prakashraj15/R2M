"use client";
// Live data provider for the original screens. The name and the useR2M() hook are kept so every screen renders
// unchanged, but nothing here is mock: the Control Plane reads/writes the R2M platform (signed demo session), and
// the Operations Desk talks to the separate OpsPilot agent service.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, request } from "@/lib/api";
import { type Command } from "@/lib/release";
import { rolesFor } from "@/lib/permissions";
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

const EMAIL: Record<Role, string> = {
  vendor_developer: "dev@atlas.demo",
  vendor_release_manager: "release@atlas.demo",
  customer_security: "security@meridian.demo",
  customer_ops: "ops@meridian.demo",
};
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
  setRole: (role: Role) => void;
  setOrg: (org: Organization) => void;
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
  e instanceof ApiError ? `${e.message} (${e.body.code})` : e instanceof Error ? e.message : "Request failed.";

export function R2MProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState>(emptyState);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [components, setComponents] = useState<ComponentInfo[]>([]);
  const [agentId, setAgentId] = useState("");
  const [installationId, setInstallationId] = useState("");
  const [role, updateRole] = useState<Role>(APP === "desk" ? "customer_ops" : "vendor_developer");
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
      setMessage(`Live data unavailable: ${errorText(e)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  // Control Plane: the role switcher is a real sign-in as the matching seeded demo identity.
  const signInAs = useCallback(async (next: Role) => {
    updateRole(next);
    if (APP === "control") {
      try {
        await api.signIn(EMAIL[next]);
      } catch (e) {
        setMessage(`Sign-in failed: ${errorText(e)}`);
      }
    }
    await refresh();
  }, [refresh]);

  useEffect(() => {
    void (async () => {
      if (APP === "control") {
        try {
          const me = await api.me();
          const current = (Object.keys(EMAIL) as Role[]).find((r) => EMAIL[r] === me.user.email);
          if (current) updateRole(current);
          else await api.signIn(EMAIL.vendor_developer);
        } catch {
          await api.signIn(EMAIL.vendor_developer).catch(() => undefined);
        }
      }
      await refresh();
    })();
  }, [refresh]);

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
        const operator = role.startsWith("vendor_") ? "vendor_developer" : "customer_ops";
        const prompt = command.prompt || "How is payments-api doing?";
        const reply = await deskRequest("/message", {
          method: "POST",
          body: JSON.stringify({ message: prompt, scenario: toLiveScenario(command.scenario), operator }),
        });
        deskRuns.current = [replyToExecution(prompt, command.scenario, reply), ...deskRuns.current];
        setMessage(reply.decision ? `R2M decision: ${reply.decision}` : "Reply received.");
        break;
      }
    }
    await refresh();
  }

  function dispatch(command: Command) {
    void run(command).catch((e) => setMessage(errorText(e)));
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
        setRole: (next) => void signInAs(next),
        setOrg: (org) => void signInAs(rolesFor[org][0]),
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
