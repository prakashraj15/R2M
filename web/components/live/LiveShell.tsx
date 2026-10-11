"use client";
import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { api, type Identity } from "@/lib/api";
import { useLive, errorText } from "./LiveProvider";
import { BrandMark } from "@/components/brand/BrandMark";
import { DemoGuide } from "@/components/demo/DemoGuide";
export function LiveShell({ children }: { children: ReactNode }) {
  const live = useLive();
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState("");
  async function reconnect() {
    setError("");
    await Promise.all([
      live.refresh(),
      api
        .identities()
        .then((r) => setIdentities(r.identities))
        .catch((e) => setError(errorText(e))),
    ]);
  }
  useEffect(() => {
    void live.refresh();
    api
      .identities()
      .then((r) => setIdentities(r.identities))
      .catch((e) => setError(errorText(e)));
  }, [live.refresh]);
  useEffect(() => {
    const focus = () => {
      if (!live.busy) void live.refresh();
    };
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, [live.refresh, live.busy]);
  async function switchIdentity(email: string) {
    setSwitching(true);
    setError("");
    try {
      if (email) await api.signIn(email);
      else await api.signOut();
      await live.refresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSwitching(false);
    }
  }
  const base = live.state ? `/agents/${live.state.agent_id}` : null;
  const query = live.state
    ? `?installation_id=${encodeURIComponent(live.state.installation_id)}`
    : "";
  return (
    <div className="live-shell">
      <header className="topbar">
        <Link href="/demo/agent" aria-label="R2M live demo">
          <BrandMark />
        </Link>
        <div className="top-actions">
          <Link href="/agents/2246399b-c8bd-5598-b1c7-32a0da4d3d96">Agent workspace</Link>
          <select
            aria-label="Backend demo identity"
            value={live.session?.user.email || ""}
            disabled={switching || live.busy || live.loading}
            onChange={(e) => switchIdentity(e.target.value)}
          >
            <option value="">Sign in / signed out</option>
            {identities.map((i) => (
              <option key={`${i.email}-${i.role}`} value={i.email}>
                {i.organization} · {i.role}
              </option>
            ))}
          </select>
          <button
            className="button"
            disabled={live.busy || live.loading || switching}
            onClick={reconnect}
          >
            Refresh
          </button>
        </div>
      </header>
      <div className="mock-strip">
        Demo authentication, not production. · Backend-connected UI · Synthetic
        service infrastructure
      </div>
      <main>
        <nav className="button-row live-nav" aria-label="Connected workspace">
          <Link className="button" href="/demo/agent">
            OpsPilot chat
          </Link>
          <Link className="button" href="/approvals">
            Approvals
          </Link>
          {base &&
            [
              ["Topology", ""],
              ["Policies", "/policies"],
              ["Evaluations & release", "/evaluations"],
              ["Traces", "/traces"],
              ["Security", "/security"],
              ["Costs", "/costs"],
              ["Evidence", "/evidence"],
            ].map(([label, path]) => (
              <Link
                key={label}
                className="button"
                href={`${base}${path}${query}`}
              >
                {label}
              </Link>
            ))}
        </nav>
        <DemoGuide />
        {(error || live.error) && (
          <div className="live-error" role="alert">
            {error || live.error}
          </div>
        )}
        {(live.loading || switching) && (
          <p role="status" className="soft-note">
            Loading backend state… Requests may take a few seconds.
          </p>
        )}
        {!live.loading && !live.session && (
          <p className="soft-note">
            Choose a demo identity above to connect. No local fixture data is
            used here.
          </p>
        )}
        {children}
      </main>
    </div>
  );
}
