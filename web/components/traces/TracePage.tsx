"use client";
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMock } from "@/components/MockProvider";
import { TraceWaterfall } from "./TraceWaterfall";
import { EventDetail } from "./EventDetail";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
export function TracePage() {
  const { state } = useMock();
  const params = useSearchParams();
  const [runId, setRunId] = useState("");
  const [spanId, setSpanId] = useState("");
  const run =
    state.runs.find((r) => r.id === runId) ||
    state.runs.find((r) => r.traceId === params.get("trace")) ||
    state.runs[0];
  const span = run.spans.find((s) => s.id === spanId) || run.spans[0];
  return (
    <>
      <PageHeader
        eyebrow="OpsPilot / Native observability"
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
          PROVENANCE <strong>Simulated</strong>
        </span>
        <Badge>{run.status.replaceAll("_", " ")}</Badge>
      </div>
      <Panel
        title="Execution waterfall"
        subtitle="Select a span for sanitized metadata"
      >
        <TraceWaterfall run={run} selected={span.id} onSelect={setSpanId} />
      </Panel>
      <div className="two-column section-gap">
        <EventDetail span={span} />
        <Panel title="Outcome & responsibility">
          <div className="panel-body">
            <p className="body-copy">{run.recommendation}</p>
            <div className="kv">
              <span>Agent owner</span>
              <strong>Atlas Applied AI</strong>
            </div>
            <div className="kv">
              <span>Customer scope</span>
              <strong>Meridian Financial</strong>
            </div>
            <div className="kv">
              <span>Historical intelligence</span>
              <Badge tone="gray">Unavailable</Badge>
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
