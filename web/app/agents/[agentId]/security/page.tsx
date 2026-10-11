"use client";
import Link from "next/link";
import { useMock } from "@/components/MockProvider";
import { policies } from "@/lib/mock-data";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
import { MetricCard } from "@/components/metrics/MetricCard";
export default function Page() {
  const { state } = useMock();
  return (
    <>
      <PageHeader
        eyebrow="OpsPilot / Controls & findings"
        title="Security posture"
        description="Connect each declared guardrail to its policy, test, and runtime evidence."
      />
      <div className="metrics-grid three">
        <MetricCard
          label="Declared guardrails"
          value="03"
          detail="Three named tool boundaries"
          accent
        />
        <MetricCard
          label="Unresolved incident"
          value={state.service.health === "Degraded" ? "01" : "00"}
          detail="Simulated post-deployment error spike"
        />
        <MetricCard
          label="Bypass resistance"
          value="Unknown"
          detail="Fixture coverage is not an attestation"
        />
      </div>
      <Panel
        title="Control mapping"
        subtitle="Observed versus proven coverage stays explicit"
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>CONTROL / POLICY</th>
                <th>ENFORCEMENT HOOK</th>
                <th>BUILD EVIDENCE</th>
                <th>RUNTIME COVERAGE</th>
              </tr>
            </thead>
            <tbody>
              {policies.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link
                      className="table-link"
                      href="/agents/opspilot/policies"
                    >
                      {p.name}
                    </Link>
                    <small>
                      {p.id} · v{p.version}
                    </small>
                  </td>
                  <td>{p.hook}</td>
                  <td>
                    <Link
                      className="text-link"
                      href="/agents/opspilot/evaluations"
                    >
                      safe-1.0 · passed ↗
                    </Link>
                  </td>
                  <td>
                    <Badge tone="gray">Simulated hook</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="section-gap">
        <Panel title="Findings & incidents">
          <div className="panel-body">
            <div className="finding">
              <Badge>
                {state.service.health === "Degraded"
                  ? "High severity"
                  : "Resolved"}
              </Badge>
              <div>
                <h3>Elevated errors after payments-api v2.1</h3>
                <p className="body-copy">
                  {state.service.health === "Degraded"
                    ? "8.4% simulated error rate. Investigate before mutation."
                    : "Service state is healthy in the current simulation."}
                </p>
              </div>
              <Link href="/demo/agent" className="text-link">
                Investigate →
              </Link>
            </div>
            <div className="soft-note">
              A separate faulty-build fixture demonstrates an unguarded rollback
              and blocks release. It is not an available production bypass
              control.
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}
