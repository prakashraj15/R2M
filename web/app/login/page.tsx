"use client";
import { useState, type FormEvent } from "react";
import { motion } from "framer-motion";
import { api, ApiError } from "@/lib/api";
import { APP, deskRequest } from "@/lib/live-adapter";
import { BrandMark } from "@/components/brand/BrandMark";
// Both apps sign in with an R2M account. The desk's agent service verifies it against R2M and issues its own cookie.
export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const desk = APP === "desk";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (desk) await deskRequest("/session", { method: "POST", body: JSON.stringify({ email, password }) });
      else await api.signIn(email, password);
      const next = new URLSearchParams(window.location.search).get("next") || "/";
      window.location.assign(next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "Invalid email or password." : err instanceof Error ? err.message : "Sign-in failed.");
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <motion.form
        className="login-card"
        onSubmit={submit}
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      >
        <BrandMark />
        <h1>{desk ? "OpsPilot operations desk" : "R2M control plane"}</h1>
        <p className="body-copy">{desk ? "Sign in with your R2M account." : "Sign in to your organization."}</p>
        <label className="field-label" htmlFor="email">EMAIL</label>
        <input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} disabled={busy} />
        <label className="field-label" htmlFor="password">PASSWORD</label>
        <input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy} />
        {error && <p role="alert" className="login-error">{error}</p>}
        <button className="button button-primary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </motion.form>
    </main>
  );
}
