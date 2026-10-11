"use client";
// Live demo console: every number and action here comes from the real backend (/api/v1), never mock data.
import { BrandMark } from "@/components/brand/BrandMark";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, request, type Identity, type Session } from "@/lib/api";

type Obj = Record<string, any>;
const SCENARIOS = ["degraded", "approval", "healthy", "faulty"] as const;
const box: React.CSSProperties = { border: "1px solid #e3e6ea", borderRadius: 12, padding: 16, background: "#fff" };
const mono: React.CSSProperties = { fontFamily: "ui-monospace, monospace", fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" };
const fmt = (v: any) => (v === null || v === undefined ? "Unknown" : typeof v === "number" ? (Math.round(v * 10000) / 10000).toString() : String(v));

export default function LivePage() {
  const [ids, setIds] = useState<Identity[]>([]);
  const [me, setMe] = useState<Session | null>(null);
  const [state, setState] = useState<Obj | null>(null);
  const [approvals, setApprovals] = useState<Obj[]>([]);
  const [policies, setPolicies] = useState<Obj[]>([]);
  const [metrics, setMetrics] = useState<Obj | null>(null);
  const [keewano, setKeewano] = useState<Obj | null>(null);
  const [incidents, setIncidents] = useState<Obj[]>([]);
  const [overview, setOverview] = useState<Obj | null>(null);
  const [turn, setTurn] = useState<Obj | null>(null);
  const [trace, setTrace] = useState<Obj | null>(null);
  const [scenario, setScenario] = useState<(typeof SCENARIOS)[number]>("degraded");
  const [msg, setMsg] = useState("payments-api is throwing errors, please fix it");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setErr("");
    try { await fn(); } catch (e) { setErr(e instanceof ApiError ? `${e.body.code}: ${e.message}` : String(e)); }
    finally { setBusy(""); }
  };

  const refresh = useCallback(async () => {
    const who = await api.me();
    const org = who.organizations[0]?.id;
    if (org) setOverview((await api.overview(org)) as Obj);
    const st = (await api.agentState()) as Obj;
    setState(st);
    const agent = st.agent_id as string, inst = st.installation_id as string;
    const [ap, po, me2, ke, inc] = await Promise.all([
      api.approvals() as Promise<Obj>,
      request<Obj>(`/agents/${agent}/policies?installation_id=${inst}`),
      request<Obj>(`/agents/${agent}/metrics?range=24h&installation_id=${inst}`),
      api.integration() as Promise<Obj>,
      request<Obj>(`/agents/${agent}/incidents?installation_id=${inst}`),
    ]);
    setApprovals((ap.approvals as Obj[]).filter((a) => a.status === "pending" || a.status === "approved").slice(0, 8));
    setPolicies(po.policies as Obj[]);
    setMetrics(me2.summary as Obj);
    setKeewano(ke);
    setIncidents((inc.incidents as Obj[]).slice(0, 5));
  }, []);

  const loadSession = useCallback(async () => {
    setIds((await api.identities()).identities);
    try { setMe(await api.me()); await refresh(); } catch (e) { if (!(e instanceof ApiError && e.status === 401)) throw e; setMe(null); }
  }, [refresh]);

  useEffect(() => { void run("Loading", loadSession); }, [loadSession]);

  const signIn = (email: string) => run("Switching identity", async () => { await api.signIn(email); await loadSession(); });
  const send = () => run("OpsPilot is working (live model + R2M gate, 20-40 s)", async () => {
    const out = (await api.message(msg, scenario as any, state?.installation_id)) as Obj;
    setTurn(out); setTrace(null); await refresh();
  });
  const reset = () => run("Resetting scenario", async () => { await api.resetScenario(scenario); setTurn(null); setTrace(null); await refresh(); });
  const decide = (id: string, decision: "approve" | "reject" | "revoke") =>
    run(`${decision}…`, async () => { await api.decision(id, decision, `${decision} from live console`); await refresh(); });
  const submit = (rev: string) => run("Submitting policy", async () => { await api.submitPolicy(state!.agent_id, rev, state!.installation_id); await refresh(); });
  const openTrace = (id: string) => run("Loading trace", async () => setTrace((await api.trace(id)) as Obj));

  const role = me?.organizations.flatMap((o) => o.roles.map((r) => `${o.name} · ${r}`)).join(", ");
  const svc = state?.services?.[0];
  const traceId = turn?.trace_id || state?.last_execution?.trace_id;

  return (
    <main style={{ maxWidth: 1280, margin: "24px auto", padding: "0 16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <BrandMark className="session-brand" />
        <h1 style={{ margin: 0 }}>Live dashboard</h1>
        <span className="soft-note" style={{ padding: "4px 10px" }}>LIVE · real backend data · demo authentication</span>
        <Link href="/" className="text-link">Dashboard (design preview)</Link>
      </div>

      <div style={{ ...box, marginTop: 16, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <strong>Acting as:</strong> <span>{me ? `${me.user.display_name} — ${role}` : "not signed in"}</span>
        <select onChange={(e) => e.target.value && signIn(e.target.value)} value="" disabled={!!busy}>
          <option value="">Switch identity…</option>
          {ids.map((i) => <option key={i.email + i.role} value={i.email}>{i.display_name} · {i.organization}</option>)}
        </select>
        <button className="button" disabled={!!busy || !me} onClick={() => run("Refreshing", refresh)}>Refresh</button>
        {busy && <span role="status">⏳ {busy}</span>}
        {err && <span role="alert" style={{ color: "#b42318" }}>{err}</span>}
      </div>

      {me && overview && (
        <section style={{ ...box, marginTop: 16 }}>
          <h2 style={{ marginTop: 0 }}>{me.organizations[0]?.name} overview · last 24h</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 12 }}>
            {[
              ["Deployed agents", fmt(overview.metrics.deployed_agents)],
              ["Run success", overview.metrics.run_success.value === null ? "Unknown" : `${Math.round(overview.metrics.run_success.value * 100)}% (${overview.metrics.run_success.completed}/${overview.metrics.run_success.finished})`],
              ["Open high-severity findings", fmt(overview.metrics.unresolved_high_severity_findings)],
              ["Policy enforcement coverage", overview.metrics.policy_enforcement_coverage.value === null ? "Unknown" : `${Math.round(overview.metrics.policy_enforcement_coverage.value * 100)}% (${overview.metrics.policy_enforcement_coverage.numerator}/${overview.metrics.policy_enforcement_coverage.denominator}, observed)`],
              ["Cost", `$${fmt(overview.metrics.cost.total_usd)} · ${Object.keys(overview.metrics.cost.by_source).join(", ") || "no usage"}`],
              ["p95 action latency", overview.metrics.p95_action_latency_ms === null ? "Unknown" : `${Math.round(overview.metrics.p95_action_latency_ms)} ms`],
            ].map(([k, v]) => (
              <div key={k} className="soft-note"><div style={{ fontSize: 12 }}>{k}</div><strong style={{ fontSize: 20 }}>{v}</strong></div>
            ))}
          </div>
          <table style={{ width: "100%", marginTop: 12, fontSize: 14 }}>
            <thead><tr style={{ textAlign: "left" }}><th>Agent</th><th>Customer</th><th>Build</th><th>Gate</th><th>Health</th><th>Open findings</th></tr></thead>
            <tbody>
              {(overview.agents as Obj[]).map((a) => (
                <tr key={a.installation_id}><td>{a.name}</td><td>{a.customer_name}</td><td>{a.build_version ?? "Unknown"}</td>
                  <td>{a.gate_status ?? "Unknown"}</td><td>{a.health}</td><td>{a.open_findings}</td></tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {me && state && (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.4fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
          <section style={box}>
            <h2 style={{ marginTop: 0 }}>OpsPilot (live agent)</h2>
            {svc && (
              <p className="body-copy">
                <strong>payments-api</strong> {svc.deployment_version} · {svc.health_status} · errors {svc.error_rate_pct}% · p95 {svc.p95_latency_ms} ms · replicas {svc.replicas}
              </p>
            )}
            <div className="button-row" style={{ flexWrap: "wrap" }}>
              <select value={scenario} onChange={(e) => setScenario(e.target.value as any)} disabled={!!busy}>
                {SCENARIOS.map((s) => <option key={s}>{s}</option>)}
              </select>
              <button className="button" disabled={!!busy} onClick={reset}>Reset scenario</button>
            </div>
            <textarea value={msg} onChange={(e) => setMsg(e.target.value)} rows={2} style={{ width: "100%", marginTop: 8 }} />
            <div className="button-row" style={{ flexWrap: "wrap" }}>
              <button className="button button-primary" disabled={!!busy || !msg} onClick={send}>Send to OpsPilot</button>
              {["payments-api is throwing errors, please fix it", "Roll back payments-api to v2.0", "approved, continue", "scale payments-api to 8 replicas", "How is payments-api doing?"].map((q) => (
                <button key={q} className="button" disabled={!!busy} onClick={() => setMsg(q)}>{q}</button>
              ))}
            </div>
            {turn && (
              <div className="soft-note" style={{ marginTop: 12 }}>
                <p><strong>Decision:</strong> {fmt(turn.decision)} {(turn.reasons || turn.reason_codes || []).join(", ")}</p>
                {turn.proposal && <p><strong>Proposal:</strong> {turn.proposal.tool} {JSON.stringify(turn.proposal.arguments)} · source: {turn.proposal.source}</p>}
                {turn.keewano && <p><strong>Keewano:</strong> {JSON.stringify(turn.keewano)}</p>}
                {turn.steps && <p><strong>Steps:</strong> {[].concat(turn.steps).join(" → ")}</p>}
                <p style={mono}>{turn.reply || turn.message}</p>
                {turn.trace_id && <button className="button" onClick={() => openTrace(turn.trace_id)}>Open trace</button>}
              </div>
            )}
            {!turn && traceId && <button className="button" onClick={() => openTrace(traceId)}>Open last trace</button>}
            {trace && (
              <div style={{ marginTop: 12 }}>
                <h3>Trace {String(trace.execution?.trace_id).slice(0, 8)} · {trace.execution?.status}</h3>
                <div style={mono}>
                  {(trace.spans as Obj[]).filter((s) => s.status !== "placeholder").map((s) => (
                    <div key={s.id}>{"  ".repeat(s.depth)}▸ [{s.kind}] {s.name} · {s.status} · {s.duration_ms ? Math.round(s.duration_ms) + " ms" : "…"}</div>
                  ))}
                </div>
                <p><strong>Policy decisions:</strong></p>
                <div style={mono}>{(trace.decisions as Obj[]).map((d) => `${d.decision.toUpperCase()} ${d.reason_code} ${d.policy_key ? `(${d.policy_key} ${d.policy_version})` : ""}`).join("\n") || "none"}</div>
                <p><strong>Grants:</strong> {(trace.grants as Obj[]).map((g) => `${g.tool_key}: applied ${g.applied_at ? "✓" : "–"} consumed ${g.consumed_at ? "✓" : "–"}`).join("; ") || "none"}</p>
                <p><strong>Model usage:</strong> {(trace.usage as Obj[]).map((u) => `${u.input_tokens}+${u.output_tokens} tok $${u.amount_usd} (${u.cost_source})`).join("; ") || "none"}</p>
              </div>
            )}
          </section>

          <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
            <section style={box}>
              <h2 style={{ marginTop: 0 }}>Approvals</h2>
              {approvals.length === 0 && <p className="body-copy">Nothing pending.</p>}
              {approvals.map((a) => (
                <div key={a.id} className="soft-note" style={{ marginBottom: 8 }}>
                  <strong>{a.kind === "policy" ? `Policy ${a.policy_key} ${a.version}` : `Action ${a.tool_key} ${JSON.stringify(a.arguments)}`}</strong> · {a.status}
                  {a.reason_code && <div style={mono}>{a.reason_code}</div>}
                  {a.can_decide && (
                    <div className="button-row">
                      <button className="button button-primary" disabled={!!busy} onClick={() => decide(a.id, "approve")}>Approve</button>
                      <button className="button" disabled={!!busy} onClick={() => decide(a.id, "reject")}>Reject</button>
                    </div>
                  )}
                </div>
              ))}
            </section>

            <section style={box}>
              <h2 style={{ marginTop: 0 }}>Policies (code-owned)</h2>
              {policies.map((p) => {
                const active = (p.submissions as Obj[]).find((s) => s.active);
                const pending = (p.submissions as Obj[]).find((s) => s.status === "pending");
                return (
                  <div key={p.id} style={{ marginBottom: 8 }}>
                    <strong>{p.policy_key}</strong> {p.version} <span style={mono}>{String(p.artifact_hash).slice(7, 19)}</span> ·{" "}
                    {active ? "ACTIVE" : pending ? "pending approval" : "not approved"} · decisions {JSON.stringify(p.operational_decisions)}
                    <div className="button-row">
                      {active && <button className="button" disabled={!!busy} onClick={() => decide(active.id, "revoke")}>Revoke (security)</button>}
                      {!active && !pending && <button className="button" disabled={!!busy} onClick={() => submit(p.id)}>Submit for approval (vendor dev)</button>}
                    </div>
                  </div>
                );
              })}
            </section>

            {metrics && (
              <section style={box}>
                <h2 style={{ marginTop: 0 }}>Cost & usage (24h)</h2>
                <p>Total cost: <strong>${fmt(metrics.cost.total_usd)}</strong> · by source {JSON.stringify(metrics.cost.by_source)}</p>
                <p>Tokens: {metrics.cost.input_tokens} in / {metrics.cost.output_tokens} out</p>
                <p>Run success: {fmt(metrics.run_success.value)} ({metrics.run_success.completed}/{metrics.run_success.finished})</p>
                <p>p95 tool latency: {fmt(metrics.p95_action_latency_ms)} ms</p>
                <p>Policy enforcement coverage: {fmt(metrics.policy_enforcement_coverage.value)} ({metrics.policy_enforcement_coverage.numerator}/{metrics.policy_enforcement_coverage.denominator})</p>
                <p className="body-copy" style={{ fontSize: 12 }}>{metrics.policy_enforcement_coverage.explanation}</p>
                <p>Open high-severity findings: {metrics.unresolved_high_severity_findings}</p>
                {incidents.map((i) => <div key={i.id} style={mono}>{i.severity.toUpperCase()} {i.category} · {i.status}</div>)}
              </section>
            )}

            {keewano && (
              <section style={box}>
                <h2 style={{ marginTop: 0 }}>Keewano</h2>
                <p>Platform enabled: {String(keewano.platform_enabled)} · adapter: {String(keewano.adapter_installed)}</p>
                {(keewano.organizations as Obj[]).map((o) => (
                  <p key={o.organization_id}>{o.name}: {o.enabled ? "ON" : "off"} · backlog {o.backlog} · dead {o.dead} · last sent {fmt(o.last_success_at)}</p>
                ))}
                <p>Last query: {keewano.last_query ? `${keewano.last_query.status} · samples ${fmt(keewano.last_query.sample_count)}` : "none yet"}</p>
              </section>
            )}
          </div>
        </div>
      )}
      {!me && !busy && <p style={{ marginTop: 16 }}>Select an identity above to sign in.</p>}
    </main>
  );
}
