"use client";
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
} from "@xyflow/react";
import type { Topology } from "@/lib/live-types";
import { metric } from "@/lib/live-types";
import { useResource, ResourceStatus } from "./useResource";
import { Panel, Badge } from "@/components/ui/shared";
export function LiveTopology({ path }: { path: string }) {
  const r = useResource<Topology>(path);
  const [selected, setSelected] = useState("");
  const component = useSearchParams().get("component");
  const nodes = useMemo<Node[]>(
    () =>
      r.data?.nodes.map((n, i) => ({
        id: n.id,
        selected: selected ? n.id === selected : n.component_key === component,
        position: { x: (i % 3) * 255, y: Math.floor(i / 3) * 130 },
        data: {
          label: (
            <>
              <strong>{n.label}</strong>
              <br />
              <small>
                {n.component_key} · {n.status || "unknown"}
              </small>
            </>
          ),
        },
        style: {
          background: "white",
          border: `2px solid ${{ healthy: "#9bc841", degraded: "#e1ad4f", critical: "#d45965" }[n.status || ""] || "#a8afb7"}`,
          borderRadius: 12,
          width: 220,
          padding: 15,
        },
      })) || [],
    [r.data, selected, component],
  );
  const edges = useMemo<Edge[]>(
    () =>
      r.data?.edges.map((e) => ({
        id: e.id,
        source: e.source_component_id,
        target: e.target_component_id,
      })) || [],
    [r.data],
  );
  const node = r.data?.nodes.find((n) =>
    selected ? n.id === selected : n.component_key === component,
  );
  return (
    <>
      <ResourceStatus {...r} />
      {r.data && (
        <>
          <div className="topology-canvas">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              fitView
              nodesDraggable={false}
              nodesConnectable={false}
              onNodeClick={(_, n) => setSelected(n.id)}
            >
              <Background />
              <Controls />
            </ReactFlow>
          </div>
          {node ? (
            <Panel
              title={node.label}
              subtitle={node.component_key}
              action={<Badge>{node.status || "Unknown"}</Badge>}
            >
              <div className="panel-body">
                <p>{node.source}</p>
                <p>
                  Calls: {metric(node.metrics?.calls)} · Errors:{" "}
                  {metric(node.metrics?.errors)} · P95:{" "}
                  {metric(node.metrics?.p95_ms, " ms")} · Cost:{" "}
                  {metric(node.metrics?.cost_usd, " USD")}
                </p>
              </div>
            </Panel>
          ) : (
            <p className="soft-note">
              Select a component for measured metrics. Missing telemetry stays
              Unknown.
            </p>
          )}
        </>
      )}
    </>
  );
}
