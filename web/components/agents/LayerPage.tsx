"use client";
// Models / Tools / Orchestration / Compute / Memory & storage: the same agent seen through one layer,
// all values from the live R2M platform (topology telemetry, metrics, policies, integrations).
import Link from "next/link";
import { useR2M } from "@/components/R2MProvider";
import { MetricCard } from "@/components/metrics/MetricCard";
import { PageHeader, Panel, Badge, Empty } from "@/components/ui/shared";
import { useLive } from "@/components/ui/useLive";
import { useState } from "react";
import { api } from "@/lib/api";

type Obj = Record<string, any>;
const titles: Record<string, string> = {
  models: "Models",
  tools: "Tools",
  orchestration: "Orchestration",
  storage: "Memory & storage",
  compute: "Compute",
};
const ms = (v: number | null | undefined) => (v == null ? "Unknown" : `${Math.round(v)} ms`);
const usd = (v: number | null | undefined) => (v == null ? "Unknown" : `$${v.toFixed(4)}`);

export function LayerPage({ layer }: { layer: string }) {
  const { state, agentId, policies, base } = useR2M();
  const { identity } = state;
  const topo = useLive<{ nodes: Obj[] }>(agentId ? `/agents/${agentId}/topology?range=24h` : null);
  const metrics = useLive<{ summary: Obj }>(agentId ? `/agents/${agentId}/metrics?range=24h` : null);
  const { role, notify } = useR2M();
  const [version, setVersion] = useState(0);
  const keewano = useLive<Obj>(layer === "orchestration" || layer === "storage" ? `/integrations/keewano?v=${version}` : null);
  async function setMirroring(orgId: string, enabled: boolean) {
    try {
      await api.configureIntegration(orgId, enabled);
      notify(`Keewano mirroring ${enabled ? "enabled" : "disabled"}.`);
      setVersion((v) => v + 1);
    } catch (e) {
      notify(e instanceof Error ? e.message : "Could not change the integration.");
    }
  }
  const ready = useLive<Obj>(layer === "storage" ? "/health/ready" : null);
  const nodes = topo?.nodes ?? [];
  const ofKind = (...kinds: string[]) => nodes.filter((n) => kinds.includes(n.kind));
  const sum = (list: Obj[], k: string) => list.reduce((a, n) => a + (n.metrics?.[k] || 0), 0);
  const worst = (list: Obj[], k: string) => {
    const v = list.map((n) => n.metrics?.[k]).filter((x) => x != null);
    return v.length ? Math.max(...v) : null;
  };
  const cost = metrics?.summary?.cost;
  const governedBy = (tool: string) => policies.filter((p) => p.tool.split(", ").includes(tool)).map((p) => p.id);
  const seen = (n: Obj) => (n.last_seen_at ? new Date(n.last_seen_at).toLocaleString() : "Never");

  return (
    <>
      <PageHeader
        eyebrow={`${identity.agent} / ${layer}`}
        title={titles[layer]}
        description="The same agent, execution records, and evidence—seen through a different layer. Live, last 24 h."
      />
      {layer === "models" ? (
        <>
          <div className="metrics-grid three">
            <MetricCard label="Model calls" value={sum(ofKind("model"), "calls")} detail="Model spans reported by the SDK" accent />
            <MetricCard label="p95 model latency" value={ms(worst(ofKind("model"), "p95_ms"))} detail="From model spans; Unknown without telemetry" />
            <MetricCard
              label="Model cost"
              value={usd(cost?.total_usd)}
              detail={cost ? `${cost.input_tokens} in / ${cost.output_tokens} out tokens · ${Object.keys(cost.by_source).join(", ") || "no usage"}` : "Loading…"}
            />
          </div>
          <Panel title="Model inventory" subtitle="Registered by the agent's SDK">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>MODEL</th><th>CALLS</th><th>ERRORS</th><th>P95</th><th>COST</th><th>LAST SEEN</th></tr>
                </thead>
                <tbody>
                  {ofKind("model").map((n) => (
                    <tr key={n.id}>
                      <td><strong>{n.label}</strong> <code>{n.component_key}</code></td>
                      <td>{n.metrics?.calls ?? 0}</td>
                      <td>{n.metrics?.errors ?? 0}</td>
                      <td>{ms(n.metrics?.p95_ms)}</td>
                      <td>{usd(n.metrics?.cost_usd)}</td>
                      <td>{seen(n)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="panel-body">
              <p className="helper">{cost?.provenance_note}</p>
              <Link href={`${base}/traces`} className="text-link">Inspect model spans →</Link>
            </div>
          </Panel>
        </>
      ) : layer === "tools" ? (
        <Panel title="Tool inventory" subtitle="Calls observed by the SDK; boundary from the agent's code-owned policies">
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>TOOL</th><th>CALLS</th><th>ERRORS</th><th>P95</th><th>BOUNDARY</th><th /></tr>
              </thead>
              <tbody>
                {ofKind("tool").map((n) => {
                  const gov = governedBy(n.component_key);
                  return (
                    <tr key={n.id}>
                      <td><code>{n.component_key}</code></td>
                      <td>{n.metrics?.calls ?? 0}</td>
                      <td>{n.metrics?.errors ?? 0}</td>
                      <td>{ms(n.metrics?.p95_ms)}</td>
                      <td>{gov.length ? <Badge tone="green">Governed · {gov.join(", ")}</Badge> : <Badge tone="gray">Observed</Badge>}</td>
                      <td><Link href={`${base}/traces`} className="text-link">Trace →</Link></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!ofKind("tool").length && <Empty title="No tools registered yet" description="Tools appear when the agent registers its topology." />}
        </Panel>
      ) : layer === "orchestration" ? (
        <>
          <Panel title="Execution lifecycle">
            <div className="lifecycle">
              {["Observe", "Diagnose", "Keewano history", "Propose", "Policy gate", "Act", "Verify"].map((s, i) => (
                <div key={s}>
                  <small>0{i + 1}</small>
                  <strong>{s}</strong>
                </div>
              ))}
            </div>
            <div className="panel-body">
              <div className="kv"><span>Recent executions</span><strong>{state.runs.length}</strong></div>
              <div className="kv"><span>Awaiting approval</span><strong>{state.runs.filter((r) => r.status === "waiting_approval").length}</strong></div>
              <div className="kv"><span>Completed</span><strong>{state.runs.filter((r) => r.status === "completed").length}</strong></div>
              <div className="kv"><span>Denied</span><strong>{state.runs.filter((r) => r.status === "rejected").length}</strong></div>
              <div className="kv"><span>Run success (24 h)</span><strong>{metrics?.summary?.run_success?.value == null ? "Unknown" : `${Math.round(metrics.summary.run_success.value * 100)}%`}</strong></div>
              <Link href={`${base}/traces`} className="text-link">Open execution waterfall →</Link>
            </div>
          </Panel>
          <div className="section-gap">
            <Panel
              title="Keewano history adapter"
              action={<Badge tone={keewano?.platform_enabled && keewano?.adapter_installed ? "green" : "gray"}>{keewano?.platform_enabled ? "Connected" : "Disabled"}</Badge>}
            >
              <div className="panel-body">
                {(keewano?.organizations ?? []).map((o: Obj) => (
                  <div className="kv" key={o.organization_id}>
                    <span>{o.name}</span>
                    <strong>{o.enabled ? "Mirroring" : "Off"} · backlog {o.backlog} · dead {o.dead} · last sent {o.last_success_at ? new Date(o.last_success_at).toLocaleString() : "never"}</strong>
                    {role === "customer_security" && keewano?.platform_enabled && (
                      <button className="button" onClick={() => void setMirroring(o.organization_id, !o.enabled)}>
                        {o.enabled ? "Turn off" : "Turn on"}
                      </button>
                    )}
                  </div>
                ))}
                <div className="kv">
                  <span>Last history query</span>
                  <strong>{keewano?.last_query ? `${keewano.last_query.status} · ${keewano.last_query.sample_count ?? "?"} samples · ${new Date(keewano.last_query.created_at).toLocaleString()}` : "None yet"}</strong>
                </div>
                <div className="soft-note">Advisory only: a Keewano answer can change the recommendation, never the policy decision.</div>
              </div>
            </Panel>
          </div>
        </>
      ) : layer === "compute" ? (
        <>
          <div className="metrics-grid three">
            <MetricCard label="Service CPU" value={`${state.service.cpu}%`} detail={`${identity.service}, the service under ${identity.agent}'s control`} />
            <MetricCard label="Memory utilization" value={`${state.service.memory}%`} detail={`p95 ${state.service.latency} ms · errors ${state.service.errorRate}%`} />
            <MetricCard label="Replica count" value={state.service.replicas} detail={`${state.service.version} · ${state.service.health}`} accent />
          </div>
          <Panel title="Agent runtime" subtitle="Compute components reported by the agent">
            <div className="table-wrap">
              <table>
                <thead><tr><th>COMPONENT</th><th>STATUS</th><th>CALLS</th><th>LAST SEEN</th></tr></thead>
                <tbody>
                  {ofKind("compute").map((n) => (
                    <tr key={n.id}><td>{n.label}</td><td><Badge>{n.status}</Badge></td><td>{n.metrics?.calls ?? 0}</td><td>{seen(n)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!ofKind("compute").length && <Empty title="No compute telemetry" description="Host CPU/memory isn't collected; the agent reports liveness through its spans." />}
          </Panel>
        </>
      ) : (
        <Panel title="Storage coverage">
          <div className="table-wrap">
            <table>
              <thead><tr><th>STORE</th><th>ROLE</th><th>CONNECTION</th></tr></thead>
              <tbody>
                <tr>
                  <td>Aiven PostgreSQL (TLS, row-level security)</td>
                  <td>Traces, policies, approvals, grants and {state.audit.length}+ evidence records</td>
                  <td><Badge tone={ready?.status === "ready" ? "green" : "red"}>{ready?.status === "ready" ? "Connected" : "Unavailable"}</Badge></td>
                </tr>
                {ofKind("memory", "storage").map((n) => (
                  <tr key={n.id}>
                    <td>{n.label}</td>
                    <td>Agent {n.kind} · {n.metrics?.calls ?? 0} calls (24 h)</td>
                    <td><Badge>{n.status}</Badge></td>
                  </tr>
                ))}
                <tr>
                  <td>Keewano</td>
                  <td>Typed event history (advisory analytics)</td>
                  <td><Badge tone={keewano?.platform_enabled ? "green" : "gray"}>{keewano?.platform_enabled ? "Mirroring" : "Disabled"}</Badge></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="panel-body">
            <p className="body-copy">The browser stores no credentials and never connects to the database directly.</p>
          </div>
        </Panel>
      )}
    </>
  );
}
