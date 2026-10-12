"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { useR2M } from "@/components/R2MProvider";
import { DESK_URL } from "@/lib/live-adapter";
import { AgentTopology } from "./AgentTopology";
import { NodeInspector } from "./NodeInspector";
import { PageHeader, Badge } from "@/components/ui/shared";
export function Workspace() {
  const { state, components, base } = useR2M();
  const { identity } = state;
  const [selected, setSelected] = useState("gateway");
  const nodes = components;
  return (
    <>
      <PageHeader
        eyebrow="Agent workspace / Architecture"
        title={identity.agent}
        description="An operations agent with clear boundaries. Every component, connected."
        actions={
          <Link className="button button-primary" href={DESK_URL}>
            Run a scenario <ArrowUpRight size={15} />
          </Link>
        }
      />
      <div className="context-row">
        <span>
          VENDOR <strong>{identity.vendor}</strong>
        </span>
        <span>
          CUSTOMER <strong>{identity.customer}</strong>
        </span>
        <span>
          ENVIRONMENT <strong>Production</strong>
        </span>
        <Badge>{state.service.health}</Badge>
      </div>
      <div className="workspace-grid">
        <section className="panel">
          <div className="panel-heading">
            <div className="tabs">
              <span className="selected">Architecture</span>
              <Link href={`${base}/traces`}>Execution traces</Link>
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
        {nodes.find((n) => n.id === selected) && <NodeInspector component={nodes.find((n) => n.id === selected)!} />}
      </div>
      <div className="section-note">
        Topology is registered by the agent's SDK. Missing telemetry remains Unknown. A
        policy denial does not mean the service is broken.
      </div>
    </>
  );
}
