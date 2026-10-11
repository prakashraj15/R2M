"use client";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  type NodeProps,
  type Node,
} from "@xyflow/react";
import { Bot, Boxes, ShieldCheck, Wrench, Cpu, Database } from "lucide-react";
import { Badge } from "@/components/ui/shared";
import type { ComponentInfo } from "@/lib/types";
type GraphNode = Node<{ component: ComponentInfo }, "component">;
const icons = {
  orchestrator: Bot,
  model: Boxes,
  gateway: ShieldCheck,
  tool: Wrench,
  compute: Cpu,
  storage: Database,
};
function ComponentNode({ data, selected }: NodeProps<GraphNode>) {
  const c = data.component;
  const Icon = icons[c.kind as keyof typeof icons] || Boxes;
  return (
    <div className={`topology-node ${selected ? "selected" : ""}`}>
      <Handle type="target" position={Position.Top} />
      <div className="node-title">
        <span>
          <Icon size={17} />
        </span>
        <strong>{c.name}</strong>
      </div>
      <div className="node-bottom">
        <span>{c.kind}</span>
        <Badge>{c.health}</Badge>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
const nodeTypes = { component: ComponentNode };
const positions = [
  { x: 170, y: 0 },
  { x: 0, y: 145 },
  { x: 340, y: 145 },
  { x: 170, y: 300 },
  { x: 0, y: 455 },
  { x: 340, y: 455 },
];
export function AgentTopology({
  components,
  selected,
  onSelect,
}: {
  components: ComponentInfo[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  const nodes: GraphNode[] = components.map((component, i) => ({
    id: component.id,
    type: "component",
    position: positions[i],
    data: { component },
    selected: component.id === selected,
  }));
  const connections = [
    ["orchestrator", "model"],
    ["orchestrator", "gateway"],
    ["model", "tools"],
    ["gateway", "tools"],
    ["tools", "service"],
    ["tools", "memory"],
  ];
  return (
    <div className="topology-canvas">
      <ReactFlow
        nodes={nodes}
        edges={connections.map(([source, target]) => ({
          id: `${source}-${target}`,
          source,
          target,
          style: { stroke: "#a9c86d", strokeWidth: 1.5 },
          type: "smoothstep",
        }))}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelect(node.id)}
        onNodeContextMenu={(event, node) => {
          event.preventDefault();
          onSelect(node.id);
        }}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        minZoom={0.45}
        maxZoom={1.5}
      >
        <Background color="#cdd8c5" gap={19} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
      <span className="canvas-caption">
        Configured topology · simulated observations
      </span>
    </div>
  );
}
