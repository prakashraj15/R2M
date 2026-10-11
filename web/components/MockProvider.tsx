"use client";
import { createContext, useContext, useState, type ReactNode } from "react";
import { initialState } from "@/lib/mock-data";
import { applyCommand, type Command } from "@/lib/mock-engine";
import { rolesFor } from "@/lib/permissions";
import type { MockState, Organization, Role } from "@/lib/types";
interface Context {
  state: MockState;
  role: Role;
  org: Organization;
  setRole: (role: Role) => void;
  setOrg: (org: Organization) => void;
  dispatch: (command: Command) => boolean;
  notify: (message: string) => void;
  reset: () => void;
}
const MockContext = createContext<Context | null>(null);
export function MockProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState(initialState);
  const [org, updateOrg] = useState<Organization>("atlas");
  const [role, updateRole] = useState<Role>("vendor_developer");
  const [message, setMessage] = useState("");
  function setOrg(next: Organization) {
    updateOrg(next);
    updateRole(rolesFor[next][0]);
  }
  function setRole(next: Role) {
    if (rolesFor[org].includes(next)) updateRole(next);
  }
  function dispatch(command: Command) {
    try {
      const next = applyCommand(state, role, command);
      setState(next);
      setMessage("Demo state updated. No external action was performed.");
      return true;
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to update demo.",
      );
      return false;
    }
  }
  return (
    <MockContext.Provider
      value={{
        state,
        role,
        org,
        setRole,
        setOrg,
        dispatch,
        notify: setMessage,
        reset: () => {
          setState(initialState());
          setMessage("Demo reset to the initial fixture.");
        },
      }}
    >
      {children}
      {message && (
        <div className="toast" role="status">
          <span>{message}</span>
          <button
            aria-label="Dismiss notification"
            onClick={() => setMessage("")}
          >
            ×
          </button>
        </div>
      )}
    </MockContext.Provider>
  );
}
export function useMock() {
  const value = useContext(MockContext);
  if (!value) throw Error("MockProvider is required");
  return value;
}
