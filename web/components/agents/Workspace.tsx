"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { useMock } from "@/components/MockProvider";
import { components } from "@/lib/topology";
import { AgentTopology } from "./AgentTopology";
import { NodeInspector } from "./NodeInspector";
import { PageHeader, Badge } from "@/components/ui/shared";
export function Workspace() {
  const { state } = useMock();
  const [selected, setSelected] = useState("gateway");
  const nodes = components(state.service.health);
  return (
    <>
      <PageHeader
        eyebrow="Agent workspace / Architecture"
        title="OpsPilot"
        description="An operations agent with clear boundaries. Every component, connected."
        actions={
          <Link className="button button-primary" href="/demo/agent">
            Run a scenario <ArrowUpRight size={15} />
          </Link>
        }
      />
      <div className="context-row">
        <span>
          VENDOR <strong>Atlas Applied AI</strong>
        </span>
        <span>
          CUSTOMER <strong>Meridian Financial</strong>
        </span>
        <span>
          ENVIRONMENT <strong>Production simulation</strong>
        </span>
        <Badge>{state.service.health}</Badge>
      </div>
      <div className="workspace-grid">
        <section className="panel">
          <div className="panel-heading">
            <div className="tabs">
              <span className="selected">Architecture</span>
              <Link href="/agents/opspilot/traces">Execution traces</Link>
            </div>
            <span className="tiny muted">6 components · Select to inspect</span>
          </div>
          <AgentTopology
            components={nodes}
            selected={selected}
            onSelect={setSelected}
          />
          <div className="graph-legend">
            <Badge>Healthy</Badge>
            <Badge>Degraded</Badge>
            <Badge>Critical</Badge>
            <Badge>Unknown</Badge>
          </div>
        </section>
        <NodeInspector component={nodes.find((n) => n.id === selected)!} />
      </div>
      <div className="section-note">
        Topology is a frontend fixture. Missing telemetry remains Unknown. A
        policy denial does not mean the service is broken.
      </div>
    </>
  );
}
