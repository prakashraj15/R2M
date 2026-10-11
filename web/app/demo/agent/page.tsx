"use client";
import { useState } from "react";
import Link from "next/link";
import type { Scenario } from "@/lib/types";
import { useMock } from "@/components/MockProvider";
import { ScenarioControls } from "@/components/demo/ScenarioControls";
import { SimulatedServiceStatus } from "@/components/demo/SimulatedServiceStatus";
import { AgentChat } from "@/components/demo/AgentChat";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
export default function Page() {
  const [scenario, setScenario] = useState<Scenario>("rollback");
  const { state } = useMock();
  const action = state.approvals.find((a) => a.kind === "action");
  return (
    <>
      <PageHeader
        eyebrow="Atlas Applied AI / Demonstrator"
        title="OpsPilot operations desk"
        description="A synthetic service. Realistic boundaries. Follow the responsibility trail."
        actions={
          <Link href="/agents/opspilot" className="button">
            View in R2M ↗
          </Link>
        }
      />
      <div className="demo-grid">
        <aside className="panel">
          <SimulatedServiceStatus />
          <ScenarioControls scenario={scenario} onChange={setScenario} />
        </aside>
        <section className="panel chat-panel">
          <div className="panel-heading">
            <h2>Operations conversation</h2>
            <Badge tone="gray">Simulated</Badge>
          </div>
          <AgentChat scenario={scenario} />
        </section>
        <div className="demo-right">
          <Panel title="Action & authorization">
            <div className="panel-body">
              {action ? (
                <>
                  <Badge>{action.status}</Badge>
                  <h3>{action.subject}</h3>
                  <p className="body-copy">{action.description}</p>
                  <pre>
                    {JSON.stringify(
                      {
                        tool: "rollback_deployment",
                        target_version: "v2.0",
                        service: "payments-api",
                        execution: action.executionId,
                      },
                      null,
                      2,
                    )}
                  </pre>
                  <Link href="/approvals" className="button button-primary">
                    Review in R2M →
                  </Link>
                </>
              ) : (
                <>
                  <h3>No action proposed yet</h3>
                  <p className="body-copy">
                    Send a message using the rollback scenario to see the policy
                    gate pause an action.
                  </p>
                </>
              )}
            </div>
          </Panel>
          <Panel title="Historical intelligence">
            <div className="panel-body">
              <Badge tone="gray">Keewano unavailable</Badge>
              <p className="body-copy">
                No connector is configured. OpsPilot uses the explicit safe
                fallback; this demo does not claim a live historical
                recommendation.
              </p>
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
