"use client";
import Link from "next/link";
import { useMock } from "@/components/MockProvider";
import { MetricCard } from "@/components/metrics/MetricCard";
import { CostChart } from "@/components/metrics/CostChart";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
import { money, duration } from "@/lib/format";
export default function Page() {
  const { state } = useMock();
  return (
    <>
      <PageHeader
        eyebrow="OpsPilot / Usage provenance"
        title="Cost & latency"
        description="Understand the cost of each execution—and what isn't measured."
        actions={<Badge tone="gray">All model costs simulated</Badge>}
      />
      <div className="metrics-grid three">
        <MetricCard
          label="Model usage"
          value={money(state.runs.reduce((n, r) => n + r.cost, 0))}
          detail="Simulated USD · one model attempt per run"
          accent
        />
        <MetricCard
          label="Cloud infrastructure"
          value="—"
          detail="No billing source connected"
        />
        <MetricCard
          label="Awaiting human review"
          value={
            state.runs.filter((r) => r.status === "waiting_approval").length
          }
          detail="Wait time not included in tool duration"
        />
      </div>
      <Panel title="Simulated model spend by execution">
        <CostChart
          kind="cost"
          data={state.runs.map((r) => ({ name: r.id, value: r.cost }))}
        />
      </Panel>
      <div className="section-gap">
        <Panel
          title="Usage ledger"
          subtitle="No observed or allocated charges in this mock"
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>EXECUTION</th>
                  <th>MODEL ATTEMPTS</th>
                  <th>COST</th>
                  <th>DURATION</th>
                  <th>PROVENANCE</th>
                </tr>
              </thead>
              <tbody>
                {state.runs.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link
                        href={`/agents/opspilot/traces?trace=${r.traceId}`}
                        className="table-link"
                      >
                        {r.id} ↗
                      </Link>
                    </td>
                    <td>1</td>
                    <td>{money(r.cost)}</td>
                    <td>
                      {duration(r.duration)}
                      {r.status === "waiting_approval" ? " + pending wait" : ""}
                    </td>
                    <td>
                      <Badge tone="gray">Simulated</Badge>
                    </td>
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
