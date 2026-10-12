"use client";
import Link from "next/link";
import { ArrowUpRight, Clock3, ShieldAlert, Unplug } from "lucide-react";
import { useR2M } from "@/components/R2MProvider";
import { MetricCard } from "@/components/metrics/MetricCard";
import { CostChart } from "@/components/metrics/CostChart";
import { AgentCard } from "@/components/agents/AgentCard";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
import { money } from "@/lib/format";
import { useLive } from "@/components/ui/useLive";
import { DESK_URL } from "@/lib/live-adapter";

type Obj = Record<string, any>;
export function Overview() {
  const { state, user, agentId, base } = useR2M();
  const { identity } = state;
  const summary = useLive<{ summary: Obj }>(agentId ? `/agents/${agentId}/metrics?range=24h` : null)?.summary;
  const keewano = useLive<Obj>("/integrations/keewano");
  const keewanoOn = !!(keewano?.platform_enabled && keewano?.adapter_installed);
  const blocked = state.builds.filter((b) => b.deploymentStatus === "blocked");
  const coverage = summary?.policy_enforcement_coverage;
  const pct = (v: number | null | undefined) => (v == null ? "Unknown" : `${Math.round(v * 100)}%`);
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
        description={`${user?.organization ?? ""} · Visibility from policy responsibility to monitored outcome.`}
        actions={
          <>
            <span className="period">Last 24h · live</span>
            <Link className="button button-primary" href={DESK_URL}>
              Open {identity.agent} <ArrowUpRight size={15} />
            </Link>
          </>
        }
      />
      <div className="metrics-grid">
        <MetricCard
          label="Deployed agents"
          value={String(summary?.deployed_agents ?? (state.builds.some((b) => b.deployed) ? 1 : 0)).padStart(2, "0")}
          detail="Installations with a deployed build"
        />
        <MetricCard
          label="Run success"
          value={summary ? pct(summary.run_success?.value) : `${Math.round((success / Math.max(1, terminal.length)) * 100)}%`}
          detail={summary ? `${summary.run_success.completed} / ${summary.run_success.finished} finished runs (24 h)` : `${success} / ${terminal.length} finished runs`}
          accent
        />
        <MetricCard
          label="High-severity findings"
          value={summary?.unresolved_high_severity_findings ?? "Unknown"}
          detail="Unresolved high or critical incidents"
        />
        <MetricCard
          label="Observed enforcement"
          value={coverage ? `${coverage.numerator} / ${coverage.denominator}` : "Unknown"}
          detail="Grant-carrying mutations at the infrastructure boundary"
        />
        <MetricCard
          label="Model cost"
          value={summary ? money(summary.cost.total_usd) : money(state.runs.reduce((n, r) => n + r.cost, 0))}
          detail={summary ? `${summary.cost.input_tokens} in / ${summary.cost.output_tokens} out tokens · infrastructure excluded` : "Infrastructure excluded"}
        />
        <MetricCard
          label="P95 action latency"
          value={summary?.p95_action_latency_ms != null ? `${Math.round(summary.p95_action_latency_ms)} ms` : latencies.length ? `${latencies[Math.ceil(latencies.length * 0.95) - 1]} ms` : "Unknown"}
          detail={`${latencies.length} completed tool calls in recent runs`}
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
              recent executions{" "}
              <small>Terminal durations · milliseconds</small>
            </span>
          </div>
          <CostChart
            data={terminal.map((r) => ({ name: r.id, value: r.duration }))}
          />
        </Panel>
        <Panel
          title="Needs attention"
          action={<span className="muted tiny">Live</span>}
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
            <Link href={`${base}/evaluations`}>
              <span className={`signal ${blocked.length ? "red" : "neutral"}`}>
                <ShieldAlert size={17} />
              </span>
              <div>
                <strong>{blocked.length ? `${blocked.length} build${blocked.length > 1 ? "s" : ""} blocked by the release gate` : "No blocked builds"}</strong>
                <p>{blocked.length ? blocked.map((b) => b.version).join(", ") : "Every evaluated build passed its gate"}</p>
                <small>Inspect build evidence →</small>
              </div>
            </Link>
            <Link href={`${base}/orchestration`}>
              <span className="signal neutral">
                <Unplug size={17} />
              </span>
              <div>
                <strong>{keewanoOn ? "Keewano is connected" : "Keewano is disconnected"}</strong>
                <p>{keewanoOn ? `Last history query: ${keewano?.last_query ? new Date(keewano.last_query.created_at).toLocaleString() : "none yet"}` : "Native trace views remain available"}</p>
                <small>View integration state →</small>
              </div>
            </Link>
          </div>
        </Panel>
      </div>
      <Panel
        title="Agent registry"
        subtitle={`Installed at ${identity.customer}`}
        action={<Badge tone="gray">01 agent</Badge>}
      >
        <AgentCard />
      </Panel>
      <div className="section-note">
        Observed coverage describes instrumented tool paths only. It does not
        prove that uninstrumented paths cannot bypass controls.
      </div>
    </>
  );
}
