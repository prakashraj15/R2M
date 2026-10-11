"use client";
import Link from "next/link";
import { ArrowUpRight, Clock3, ShieldAlert, Unplug } from "lucide-react";
import { useMock } from "@/components/MockProvider";
import { MetricCard } from "@/components/metrics/MetricCard";
import { CostChart } from "@/components/metrics/CostChart";
import { AgentCard } from "@/components/agents/AgentCard";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
import { money } from "@/lib/format";
export default function Overview() {
  const { state, org } = useMock();
  const terminal = state.runs.filter((r) => r.status !== "waiting_approval");
  const success = terminal.filter((r) => r.status === "completed").length;
  const pending = state.approvals.filter((a) => a.status === "pending").length;
  const latencies = state.runs
    .flatMap((r) =>
      r.spans
        .filter((s) => s.kind === "tool" && s.status === "passed")
        .map((s) => s.duration),
    )
    .sort((a, b) => a - b);
  return (
    <>
      <PageHeader
        eyebrow="Your AI operations, accountable by design"
        title="Organization overview"
        description={`${org === "atlas" ? "Atlas Applied AI" : "Meridian Financial"} · Visibility from policy responsibility to monitored outcome.`}
        actions={
          <>
            <span className="period">Last 24h · fixed fixture</span>
            <Link className="button button-primary" href="/demo/agent">
              Open OpsPilot <ArrowUpRight size={15} />
            </Link>
          </>
        }
      />
      <div className="metrics-grid">
        <MetricCard
          label="Deployed agents"
          value={state.builds.some((b) => b.deployed) ? "01" : "00"}
          detail="One demo installation · release required"
        />
        <MetricCard
          label="Run success"
          value={`${Math.round((success / Math.max(1, terminal.length)) * 100)}%`}
          detail={`${success} / ${terminal.length} terminal fixture runs`}
          accent
        />
        <MetricCard
          label="High-severity findings"
          value={state.service.health === "Degraded" ? 1 : 0}
          detail="Unresolved simulated service incident"
        />
        <MetricCard
          label="Observed enforcement"
          value="3 / 3"
          detail="Declared hooks · fixture evidence only"
        />
        <MetricCard
          label="Model cost"
          value={money(state.runs.reduce((n, r) => n + r.cost, 0))}
          detail="Simulated · infrastructure excluded"
        />
        <MetricCard
          label="P95 tool latency"
          value={`${latencies[Math.ceil(latencies.length * 0.95) - 1] || 0} ms`}
          detail={`${latencies.length} simulated completed calls`}
        />
      </div>
      <div className="overview-grid">
        <Panel
          title="Execution activity"
          subtitle="Each run leaves a connected record"
          action={<Badge tone="gray">{state.runs.length} runs</Badge>}
        >
          <div className="chart-summary">
            <strong>{state.runs.length.toString().padStart(2, "0")}</strong>
            <span>
              simulated executions{" "}
              <small>Terminal durations · milliseconds</small>
            </span>
          </div>
          <CostChart
            data={terminal.map((r) => ({ name: r.id, value: r.duration }))}
          />
        </Panel>
        <Panel
          title="Needs attention"
          action={<span className="muted tiny">Current demo state</span>}
        >
          <div className="attention-list">
            <Link href="/approvals">
              <span className="signal amber">
                <Clock3 size={17} />
              </span>
              <div>
                <strong>{pending} requests need review</strong>
                <p>Policy revisions and exact-action approvals</p>
                <small>Open review center →</small>
              </div>
            </Link>
            <Link href="/agents/opspilot/evaluations">
              <span className="signal red">
                <ShieldAlert size={17} />
              </span>
              <div>
                <strong>Faulty build blocked</strong>
                <p>Mandatory rollback guard test failed</p>
                <small>Inspect build evidence →</small>
              </div>
            </Link>
            <Link href="/agents/opspilot/orchestration">
              <span className="signal neutral">
                <Unplug size={17} />
              </span>
              <div>
                <strong>Keewano is disconnected</strong>
                <p>Native trace views remain available</p>
                <small>View integration state →</small>
              </div>
            </Link>
          </div>
        </Panel>
      </div>
      <Panel
        title="Agent registry"
        subtitle="Installed at Meridian Financial"
        action={<Badge tone="gray">01 agent</Badge>}
      >
        <AgentCard />
      </Panel>
      <div className="section-note">
        Observed coverage describes these simulated hooks only. It does not
        prove that uninstrumented tool paths cannot bypass controls.
      </div>
    </>
  );
}
