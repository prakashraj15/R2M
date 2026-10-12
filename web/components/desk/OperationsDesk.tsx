"use client";
import { useState } from "react";
import Link from "next/link";
import type { Scenario } from "@/lib/types";
import { useR2M } from "@/components/R2MProvider";
import { ScenarioControls } from "@/components/desk/ScenarioControls";
import { ServiceStatus } from "@/components/desk/ServiceStatus";
import { AgentChat } from "@/components/desk/AgentChat";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
import { cp } from "@/lib/live-adapter";
export function OperationsDesk() {
  const [scenario, setScenario] = useState<Scenario>("rollback");
  const { state, reset } = useR2M();
  const action = state.approvals.find((a) => a.kind === "action");
  const latest = state.runs[0];
  const insight = state.runs.find((r) => r.insight)?.insight;
  return (
    <>
      <PageHeader
        eyebrow="Atlas Applied AI / OpsPilot"
        title="OpsPilot operations desk"
        description="Ask OpsPilot about payments-api. Every change it proposes is decided by your R2M policies."
        actions={
          <a href={cp("/agents/opspilot")} className="button">
            View in R2M ↗
          </a>
        }
      />
      <div className="demo-grid">
        <aside className="panel">
          <ServiceStatus />
          <ScenarioControls
            scenario={scenario}
            onChange={(s) => {
              setScenario(s);
              reset(s); // live: put payments-api into this scenario's baseline
            }}
          />
        </aside>
        <section className="panel chat-panel">
          <div className="panel-heading">
            <h2>Operations conversation</h2>
            <Badge tone="green">Live agent</Badge>
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
                      { ...(latest?.proposal ?? {}), service: "payments-api", trace: action.executionId },
                      null,
                      2,
                    )}
                  </pre>
                  {action.status === "pending" ? (
                    <a href={cp("/approvals")} className="button button-primary">
                      Review in R2M →
                    </a>
                  ) : action.status === "approved" ? (
                    <p className="body-copy">Approved. Send “approved, continue” to resume the same action.</p>
                  ) : null}
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
              {insight ? (
                <>
                  <Badge tone={insight.status === "ok" ? "green" : "gray"}>
                    {insight.status === "ok" ? "Keewano consulted" : `Keewano ${insight.status ?? "unavailable"}`}
                  </Badge>
                  <p className="body-copy">
                    {insight.supported
                      ? `Past outcomes support this remediation (${insight.sample_count ?? "?"} incidents). Advisory only: the R2M policy still decides.`
                      : "Not enough history; OpsPilot uses the safe fallback and does not claim a Keewano-informed recommendation."}
                  </p>
                  <pre>{JSON.stringify(insight, null, 2).slice(0, 600)}</pre>
                </>
              ) : (
                <>
                  <Badge tone="gray">Not consulted yet</Badge>
                  <p className="body-copy">
                    OpsPilot asks Keewano which past fix worked when payments-api is degraded.
                  </p>
                </>
              )}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
