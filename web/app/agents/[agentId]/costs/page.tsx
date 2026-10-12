"use client";
import Link from "next/link";
import { useR2M } from "@/components/R2MProvider";
import { MetricCard } from "@/components/metrics/MetricCard";
import { CostChart } from "@/components/metrics/CostChart";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
import { useLive } from "@/components/ui/useLive";
import { money, duration } from "@/lib/format";
type Summary = { cost: { total_usd: number; by_source: Record<string, number>; input_tokens: number; output_tokens: number; provenance_note: string } };
export default function Page() {
  const { state, agentId, base } = useR2M();
  const { identity } = state;
  const m = useLive<{ summary: Summary }>(agentId ? `/agents/${agentId}/metrics?range=24h` : null)?.summary;
  const sources = Object.keys(m?.cost.by_source ?? {});
  return (
    <>
      <PageHeader
        eyebrow={`${state.identity.agent} / Usage provenance`}
        title="Cost & latency"
        description="Understand the cost of each execution—and what isn't measured."
        actions={<Badge tone={sources.length ? "green" : "gray"}>{sources.length ? `Cost source: ${sources.join(", ")}` : "No usage in 24 h"}</Badge>}
      />
      <div className="metrics-grid three">
        <MetricCard
          label="Model usage (24 h)"
          value={m ? money(m.cost.total_usd) : "Unknown"}
          detail={m ? `${m.cost.input_tokens} in / ${m.cost.output_tokens} out tokens` : "Loading…"}
          accent
        />
        <MetricCard label="Cloud infrastructure" value="Not metered" detail="No cloud billing source is connected to R2M" />
        <MetricCard
          label="Awaiting human review"
          value={state.runs.filter((r) => r.status === "waiting_approval").length}
          detail="Wait time not included in tool duration"
        />
      </div>
      <Panel title="Model spend by execution" subtitle={m?.cost.provenance_note}>
        <CostChart kind="cost" data={state.runs.map((r) => ({ name: r.id, value: r.cost }))} />
      </Panel>
      <div className="section-gap">
        <Panel title="Usage ledger" subtitle="Per execution, from the agent's reported model usage">
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>EXECUTION</th><th>MODEL CALLS</th><th>COST</th><th>DURATION</th><th>PROVENANCE</th></tr>
              </thead>
              <tbody>
                {state.runs.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link href={`${base}/traces?trace=${r.traceId}`} className="table-link">{r.id} ↗</Link>
                    </td>
                    <td>{r.modelCalls ?? 0}</td>
                    <td>{money(r.cost)}</td>
                    <td>{duration(r.duration)}{r.status === "waiting_approval" ? " + pending wait" : ""}</td>
                    <td>{(r.costSources?.length ? r.costSources : ["none"]).map((s) => <Badge key={s} tone={s === "none" ? "gray" : "green"}>{s}</Badge>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </>
  );
}
