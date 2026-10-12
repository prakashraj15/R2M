"use client";
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useR2M } from "@/components/R2MProvider";
import { TraceWaterfall } from "./TraceWaterfall";
import { EventDetail } from "./EventDetail";
import { PageHeader, Panel, Badge, Empty } from "@/components/ui/shared";
export function TracePage() {
  const { state } = useR2M();
  const params = useSearchParams();
  const [runId, setRunId] = useState("");
  const [spanId, setSpanId] = useState("");
  const run =
    state.runs.find((r) => r.id === runId) ||
    state.runs.find((r) => r.traceId === params.get("trace")) ||
    state.runs[0];
  if (!run)
    return (
      <>
        <PageHeader eyebrow={`${state.identity.agent} / Native observability`} title="Execution traces" description="Follow the path from observation to decision and verified effect." />
        <Empty title="No executions yet" description="Traces appear when the agent reports a run through the R2M SDK." />
      </>
    );
  const span = run.spans.find((s) => s.id === spanId) || run.spans[0];
  return (
    <>
      <PageHeader
        eyebrow={`${state.identity.agent} / Native observability`}
        title="Execution traces"
        description="Follow the path from observation to decision and verified effect."
        actions={
          <select
            aria-label="Select execution"
            value={run.id}
            onChange={(e) => {
              setRunId(e.target.value);
              setSpanId("");
            }}
          >
            {state.runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.id} · {r.scenario}
              </option>
            ))}
          </select>
        }
      />
      <div className="context-row">
        <span>
          TRACE <strong>{run.traceId}</strong>
        </span>
        <span>
          PROVENANCE <strong>R2M SDK</strong>
        </span>
        <Badge>{run.status.replaceAll("_", " ")}</Badge>
      </div>
      <Panel
        title="Execution waterfall"
        subtitle="Select a span for sanitized metadata"
      >
        <TraceWaterfall run={run} selected={span?.id ?? ""} onSelect={setSpanId} />
      </Panel>
      <div className="two-column section-gap">
        {span ? <EventDetail span={span} /> : <Empty title="No spans" description="This execution reported no spans." />}
        <Panel title="Outcome & responsibility">
          <div className="panel-body">
            <p className="body-copy">{run.recommendation}</p>
            <div className="kv">
              <span>Agent owner</span>
              <strong>{state.identity.vendor}</strong>
            </div>
            <div className="kv">
              <span>Customer scope</span>
              <strong>{state.identity.customer}</strong>
            </div>
            <div className="kv">
              <span>Historical intelligence</span>
              {run.insight ? (
                <Badge tone="green">Keewano · {run.insight.status ?? "answered"}</Badge>
              ) : (
                <Badge tone="gray">Not consulted</Badge>
              )}
            </div>
            <div className="soft-note">
              Approval wait is separate from tool duration. Parallel and nested
              spans are not added together as total latency.
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}
