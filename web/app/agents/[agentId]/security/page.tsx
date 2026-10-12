"use client";
import Link from "next/link";
import { useState } from "react";
import { useR2M } from "@/components/R2MProvider";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
import { MetricCard } from "@/components/metrics/MetricCard";
import { useLive } from "@/components/ui/useLive";
import { request } from "@/lib/api";
import { DESK_URL } from "@/lib/live-adapter";

type Incident = { id: string; severity: string; status: string; category: string; description: string; detected_at: string; trace_id: string | null };
type Coverage = { value: number | null; numerator: number; denominator: number; explanation: string };

export default function Page() {
  const { state, policies, agentId, notify } = useR2M();
  const [version, setVersion] = useState(0);
  const incidents = useLive<{ incidents: Incident[] }>(agentId ? `/agents/${agentId}/incidents?limit=50&v=${version}` : null)?.incidents ?? [];
  const coverage = useLive<{ summary: { policy_enforcement_coverage: Coverage } }>(agentId ? `/agents/${agentId}/metrics?range=24h` : null)
    ?.summary.policy_enforcement_coverage;
  const open = incidents.filter((i) => i.status !== "resolved");
  const deployed = state.builds.find((b) => b.deployed);
  const evalsPassed = deployed?.gate?.evaluations;

  async function resolve(id: string) {
    try {
      await request(`/incidents/${id}`, { method: "PATCH", body: JSON.stringify({ status: "resolved", note: "Resolved from the security workspace" }) });
      notify("Incident resolved.");
      setVersion((v) => v + 1);
    } catch (e) {
      notify(e instanceof Error ? e.message : "Could not update the incident.");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="OpsPilot / Controls & findings"
        title="Security posture"
        description="Connect each declared guardrail to its policy, test, and runtime evidence."
      />
      <div className="metrics-grid three">
        <MetricCard label="Declared guardrails" value={String(policies.length).padStart(2, "0")} detail="Code-owned policies registered by the agent" accent />
        <MetricCard
          label="Unresolved incidents"
          value={String(open.length).padStart(2, "0")}
          detail={open.filter((i) => ["high", "critical"].includes(i.severity)).length + " high or critical"}
        />
        <MetricCard
          label="Bypass resistance"
          value={coverage?.value == null ? "Unknown" : `${Math.round(coverage.value * 100)}%`}
          detail={coverage ? `${coverage.numerator}/${coverage.denominator} mutations carried a grant (observed)` : "Observed coverage, not an attestation"}
        />
      </div>
      <Panel title="Control mapping" subtitle={coverage?.explanation ?? "Observed versus proven coverage stays explicit"}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>CONTROL / POLICY</th><th>ENFORCEMENT HOOK</th><th>BUILD EVIDENCE</th><th>RUNTIME STATUS</th></tr>
            </thead>
            <tbody>
              {policies.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link className="table-link" href="/agents/opspilot/policies">{p.name}</Link>
                    <small>{p.id} · v{p.version} · {p.tool}</small>
                  </td>
                  <td>{p.hook}</td>
                  <td>
                    <Link className="text-link" href="/agents/opspilot/evaluations">
                      {deployed ? `${deployed.version} · ${evalsPassed ? "passed" : "not passed"} ↗` : "No deployed build ↗"}
                    </Link>
                  </td>
                  <td><Badge tone={p.permission === "Approved" ? "green" : "amber"}>{p.permission}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="section-gap">
        <Panel title="Findings & incidents" subtitle="Opened by R2M from runtime evidence; an intended policy denial is not an incident">
          <div className="panel-body">
            {incidents.slice(0, 12).map((i) => (
              <div className="finding" key={i.id}>
                <Badge tone={i.status === "resolved" ? "green" : ["high", "critical"].includes(i.severity) ? "red" : "amber"}>
                  {i.status === "resolved" ? "Resolved" : `${i.severity} severity`}
                </Badge>
                <div>
                  <h3>{i.category.replaceAll("_", " ")}</h3>
                  <p className="body-copy">{i.description} · {new Date(i.detected_at).toLocaleString()}</p>
                </div>
                {i.trace_id && <Link href={`/agents/opspilot/traces?trace=${i.trace_id}`} className="text-link">Trace →</Link>}
                {i.status !== "resolved" && (
                  <button className="button" onClick={() => void resolve(i.id)}>Resolve</button>
                )}
              </div>
            ))}
            {!incidents.length && <p className="body-copy">No findings recorded.</p>}
            <div className="soft-note">
              The faulty build demonstrates an unguarded rollback: the infrastructure refuses it, R2M opens a critical
              incident, and the release gate blocks the build. <a className="text-link" href={DESK_URL}>Investigate in OpsPilot →</a>
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}
