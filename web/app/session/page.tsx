"use client";
import { BrandMark } from "@/components/brand/BrandMark";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError, type Identity, type Session } from "@/lib/api";
export default function SessionPage() {
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  async function load() {
    setBusy(true);
    setError("");
    setSession(null);
    try {
      const picker = await api.identities();
      setIdentities(picker.identities);
      try {
        setSession(await api.me());
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 401)) throw e;
      }
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Backend unavailable. Start the API on port 8000 and retry.",
      );
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function change(signOut = false) {
    setBusy(true);
    setError("");
    setSession(null);
    try {
      if (signOut) await api.signOut();
      else {
        await api.signIn(email);
        setSession(await api.me());
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Session request failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main style={{ maxWidth: 800, margin: "40px auto" }}>
      <BrandMark className="session-brand" />
      <Link href="/" className="text-link">
        ← Return to mock preview
      </Link>
      <h1>Backend demo session</h1>
      <p className="body-copy">Demo authentication, not production.</p>
      <div className="panel panel-body">
        <p className="body-copy">
          This page calls the backend. The existing dashboard remains a separate
          local mock preview; its role selectors do not change this session.
        </p>
        {busy && <p role="status">Connecting…</p>}
        {error && <p role="alert">{error}</p>}
        <label className="field-label" htmlFor="identity">
          Demo identity
        </label>
        <select
          id="identity"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={busy}
        >
          <option value="">Select an identity</option>
          {identities.map((i) => (
            <option key={`${i.email}-${i.role}`} value={i.email}>
              {i.display_name} · {i.organization} · {i.role}
            </option>
          ))}
        </select>
        <div className="button-row">
          <button
            className="button button-primary"
            disabled={busy || !email}
            onClick={() => change()}
          >
            Switch identity
          </button>
          <button
            className="button"
            disabled={busy}
            onClick={() => change(true)}
          >
            Sign out
          </button>
          <button className="button" disabled={busy} onClick={load}>
            Refresh session
          </button>
        </div>
        {session ? (
          <>
            <h2>{session.user.display_name}</h2>
            <p>{session.user.email}</p>
            {session.organizations.map((org) => (
              <div className="soft-note" key={org.id}>
                <strong>{org.name}</strong>
                <p>{org.roles.join(", ")}</p>
                <p>Permissions: {org.permissions.join(", ") || "Read only"}</p>
              </div>
            ))}
          </>
        ) : (
          !busy &&
          !error && <p>No active session. Select a demo identity to sign in.</p>
        )}
      </div>
    </main>
  );
}
