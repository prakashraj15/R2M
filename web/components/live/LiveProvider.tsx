"use client";
import {
  createContext,
  useContext,
  useState,
  useRef,
  useCallback,
  type ReactNode,
} from "react";
import { api, ApiError, type Session } from "@/lib/api";
import type { DemoState, AgentReply, LiveScenario } from "@/lib/live-types";
export function errorText(e: unknown) {
  if (e instanceof ApiError) {
    const text =
      e.body.code === "no_active_deployment"
        ? "No deployed build. Complete Evaluate → Deploy."
        : e.body.code === "agent_error"
          ? "OpsPilot failed; see trace."
          : e.body.code === "http_error" && e.status >= 500
            ? "Backend unavailable. Start the API on port 8000, then refresh."
            : e.message;
    return `${text}${e.body.request_id ? ` Request ID: ${e.body.request_id}` : ""}`;
  }
  return "Backend unavailable. Check that the API is running, then refresh. No action was retried.";
}
function useLiveState() {
  const [session, setSession] = useState<Session | null>(null);
  const [state, setState] = useState<DemoState | null>(null);
  const [turns, setTurns] = useState<
    { prompt: string; response: AgentReply }[]
  >([]);
  const [scenario, setScenario] = useState<LiveScenario>("healthy");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const user = useRef("");
  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const me = await api.me();
      if (user.current !== me.user.id) {
        setTurns([]);
        setState(null);
        user.current = me.user.id;
      }
      setSession(me);
      const next = await api.agentState();
      setState(next);
    } catch (e) {
      setState(null);
      if (e instanceof ApiError && e.status === 401) {
        setSession(null);
        setTurns([]);
        user.current = "";
      }
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, []);
  async function send(message: string) {
    if (lock.current || !message.trim() || !state) return false;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const response = await api.message(
        message.trim(),
        scenario,
        state.installation_id,
      );
      setTurns((old) => [...old, { prompt: message.trim(), response }]);
      try {
        setState(await api.agentState(state.installation_id));
      } catch (e) {
        setState(null);
        setError(`Reply received, but service refresh failed. ${errorText(e)}`);
      }
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function reset(next: LiveScenario) {
    if (lock.current || !state) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await api.resetScenario(next, state.installation_id);
      setScenario(next);
      setTurns([]);
      setState(await api.agentState(state.installation_id));
    } catch (e) {
      setState(null);
      setError(errorText(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  function can(permission: string, org?: string) {
    return !!session?.organizations.some(
      (o) => (!org || o.id === org) && o.permissions.includes(permission),
    );
  }
  return {
    session,
    state,
    turns,
    scenario,
    busy,
    loading,
    error,
    refresh,
    send,
    reset,
    can,
  };
}
const Context = createContext<ReturnType<typeof useLiveState> | null>(null);
export function LiveProvider({ children }: { children: ReactNode }) {
  const value = useLiveState();
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useLive() {
  const value = useContext(Context);
  if (!value) throw Error("LiveProvider required");
  return value;
}
