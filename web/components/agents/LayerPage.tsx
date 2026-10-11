"use client";
import Link from "next/link";
import { useMock } from "@/components/MockProvider";
import { MetricCard } from "@/components/metrics/MetricCard";
import { PageHeader, Panel, Badge, Empty } from "@/components/ui/shared";
const titles: Record<string, string> = {
  models: "Models",
  tools: "Tools",
  orchestration: "Orchestration",
  storage: "Memory & storage",
  compute: "Compute",
};
export function LayerPage({ layer }: { layer: string }) {
  const { state } = useMock();
  const toolNames = [
    "get_service_health",
    "read_logs",
    "get_deployment_history",
    "restart_service",
    "scale_instances",
    "rollback_deployment",
  ];
  const spans = state.runs.flatMap((r) => r.spans);
  return (
    <>
      <PageHeader
        eyebrow={`OpsPilot / ${layer}`}
        title={titles[layer]}
        description="The same agent, execution records, and evidence—seen through a different layer."
      />
      {layer === "models" ? (
        <>
          <div className="metrics-grid three">
            <MetricCard
              label="Model attempts"
              value={state.runs.length}
              detail="One simulated proposal per execution"
              accent
            />
            <MetricCard
              label="Request duration"
              value="640 ms"
              detail="Deterministic fixture value"
            />
            <MetricCard
              label="Provider connection"
              value="None"
              detail="No LLM API or credentials used"
            />
          </div>
          <Panel title="Model inventory">
            <div className="panel-body">
              <h3>OpsPilot deterministic model</h3>
              <p className="body-copy">
                Intent and proposal generation are simulated. No live-model
                performance or quality claim is made.
              </p>
              <Link href="/agents/opspilot/traces" className="text-link">
                Inspect model spans →
              </Link>
            </div>
          </Panel>
        </>
      ) : layer === "tools" ? (
        <Panel
          title="Tool inventory"
          subtitle="All mutation tools target synthetic service records"
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>TOOL</th>
                  <th>OBSERVED ATTEMPTS</th>
                  <th>COMPLETED</th>
                  <th>BOUNDARY</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {toolNames.map((t) => {
                  const calls = spans.filter(
                    (s) => s.name === t && s.status !== "not_reached",
                  );
                  return (
                    <tr key={t}>
                      <td>
                        <code>{t}</code>
                      </td>
                      <td>{calls.length}</td>
                      <td>
                        {calls.filter((s) => s.status === "passed").length}
                      </td>
                      <td>
                        <Badge tone="gray">Simulated</Badge>
                      </td>
                      <td>
                        <Link
                          href="/agents/opspilot/traces"
                          className="text-link"
                        >
                          Trace →
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      ) : layer === "orchestration" ? (
        <>
          <Panel title="Execution lifecycle">
            <div className="lifecycle">
              {[
                "Observe",
                "Diagnose",
                "Propose",
                "Policy gate",
                "Act",
                "Verify",
              ].map((s, i) => (
                <div key={s}>
                  <small>0{i + 1}</small>
                  <strong>{s}</strong>
                </div>
              ))}
            </div>
            <div className="panel-body">
              <div className="kv">
                <span>Awaiting approval</span>
                <strong>
                  {
                    state.runs.filter((r) => r.status === "waiting_approval")
                      .length
                  }
                </strong>
              </div>
              <div className="kv">
                <span>Completed</span>
                <strong>
                  {state.runs.filter((r) => r.status === "completed").length}
                </strong>
              </div>
              <Link href="/agents/opspilot/traces" className="text-link">
                Open execution waterfall →
              </Link>
            </div>
          </Panel>
          <div className="section-gap">
            <Panel
              title="Keewano history adapter"
              action={<Badge tone="gray">Disconnected</Badge>}
            >
              <div className="panel-body">
                <p className="body-copy">
                  Optional historical analytics is not configured.
                  Recommendations use the safe diagnose/escalate fallback. An
                  analytics answer must never override policy authorization.
                </p>
                <div className="soft-note">
                  Live ingestion, MCP discovery, and query behavior belong to
                  the backend handoff.
                </div>
              </div>
            </Panel>
          </div>
        </>
      ) : layer === "compute" ? (
        <>
          <div className="metrics-grid three">
            <MetricCard
              label="Service CPU"
              value={`${state.service.cpu}%`}
              detail="Simulated service state—not host telemetry"
            />
            <MetricCard
              label="Memory utilization"
              value={`${state.service.memory}%`}
              detail="Simulated service state"
            />
            <MetricCard
              label="Replica count"
              value={state.service.replicas}
              detail="Synthetic payments-api replicas"
              accent
            />
          </div>
          <Panel title="Infrastructure connection">
            <Empty
              title="Cloud telemetry isn't connected"
              description="Real process CPU, GPU, host memory, and cloud charges remain unknown. These simulated service values do not measure your computer."
            />
          </Panel>
        </>
      ) : (
        <Panel title="Storage coverage">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>STORE</th>
                  <th>ROLE</th>
                  <th>CONNECTION</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Browser fixture</td>
                  <td>Mock state and evidence references</td>
                  <td>
                    <Badge tone="gray">Session only</Badge>
                  </td>
                </tr>
                <tr>
                  <td>Aiven PostgreSQL</td>
                  <td>Planned native trace and policy persistence</td>
                  <td>
                    <Badge tone="gray">Not connected</Badge>
                  </td>
                </tr>
                <tr>
                  <td>Agent memory</td>
                  <td>Future instrumented memory operations</td>
                  <td>
                    <Badge tone="gray">Unknown</Badge>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="panel-body">
            <p className="body-copy">
              The frontend stores no credentials and does not connect directly
              to the database.
            </p>
          </div>
        </Panel>
      )}
    </>
  );
}
