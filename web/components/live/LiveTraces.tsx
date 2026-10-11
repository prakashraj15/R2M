"use client";
import { useState } from "react";
import Link from "next/link";
import { useResource, ResourceStatus } from "./useResource";
import { Panel, Badge } from "@/components/ui/shared";
interface TraceData {
  execution: { id: string; status: string; started_at: string };
  redacted_for_customer: boolean;
  spans: {
    id: string;
    name: string;
    kind: string;
    depth: number;
    started_at: string;
    duration_ms: number | null;
    status: string;
    attributes: Record<string, unknown>;
  }[];
  usage: { cost_source: string; amount_usd: number }[];
  events: unknown[];
  actions: unknown[];
  decisions: unknown[];
  grants: unknown[];
  approvals: unknown[];
  insights: unknown[];
}
function privateFields(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(privateFields);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [
        k,
        /^(prompt|completion|system_prompt|vendor_)/i.test(k)
          ? "[vendor-private]"
          : privateFields(v),
      ]),
    );
  return value;
}
function Detail({
  trace,
  base,
  query,
}: {
  trace: string;
  base: string;
  query: string;
}) {
  const r = useResource<TraceData>(`/traces/${encodeURIComponent(trace)}`);
  const [selected, setSelected] = useState("");
  const data = r.data;
  const span = data?.spans.find((s) => s.id === selected);
  const start = data ? Date.parse(data.execution.started_at) : 0;
  const total = data
    ? Math.max(
        1,
        ...data.spans.map(
          (s) =>
            Math.max(0, Date.parse(s.started_at) - start) +
            (s.duration_ms || 0),
        ),
      )
    : 1;
  return (
    <>
      <ResourceStatus {...r} />
      {data && (
        <>
          <div className="context-row">
            <span>TRACE {trace}</span>
            <Badge>{data.execution.status}</Badge>
            <span>
              {data.redacted_for_customer
                ? "Customer view · [vendor-private] attributes redacted"
                : "Vendor view"}
            </span>
          </div>
          <Panel title="Execution waterfall">
            <div className="panel-body">
              {data.spans.map((s) => (
                <button
                  className="live-span"
                  key={s.id}
                  onClick={() => setSelected(s.id)}
                >
                  <span style={{ paddingLeft: Math.min(s.depth, 12) * 12 }}>
                    {s.name}
                    <small>
                      {s.kind} · {s.status}
                    </small>
                  </span>
                  <span className="live-span-track">
                    <i
                      style={{
                        marginLeft: `${(Math.max(0, Date.parse(s.started_at) - start) / total) * 100}%`,
                        width: `${Math.max(0.6, ((s.duration_ms || 0) / total) * 100)}%`,
                      }}
                    />
                  </span>
                  <span>
                    {s.duration_ms == null ? "Unknown" : `${s.duration_ms} ms`}
                  </span>
                </button>
              ))}
            </div>
          </Panel>
          {span && (
            <Panel
              title={span.name}
              subtitle={`Component: ${String(span.attributes?.component || span.attributes?.component_key || "Unknown")}`}
            >
              {typeof span.attributes?.component === "string" && (
                <Link
                  className="text-link"
                  href={`${base}?${query}&component=${encodeURIComponent(span.attributes.component)}`}
                >
                  Show component in topology
                </Link>
              )}
              <pre>
                {JSON.stringify(
                  data.redacted_for_customer
                    ? privateFields(span.attributes)
                    : span.attributes,
                  null,
                  2,
                )}
              </pre>
            </Panel>
          )}
          <Panel title="Usage provenance">
            <div className="panel-body">
              {data.usage.map((u, i) => (
                <p key={i}>
                  {u.cost_source}: ${u.amount_usd}{" "}
                  {u.cost_source === "estimated"
                    ? "· list-price estimate, not an invoice"
                    : ""}
                </p>
              ))}
              {!data.usage.length && <p>No usage records.</p>}
            </div>
          </Panel>
          {(
            [
              "events",
              "actions",
              "decisions",
              "grants",
              "approvals",
              "insights",
            ] as const
          ).map((k) => (
            <details className="panel panel-body" key={k}>
              <summary>
                {k} · {data[k].length}
              </summary>
              <pre>
                {JSON.stringify(
                  data.redacted_for_customer ? privateFields(data[k]) : data[k],
                  null,
                  2,
                )}
              </pre>
            </details>
          ))}
        </>
      )}
    </>
  );
}
export function LiveTraces({
  path,
  trace,
  base,
  query,
}: {
  path: string;
  trace: string | null;
  base: string;
  query: string;
}) {
  const [cursor, setCursor] = useState("");
  const r = useResource<{
    traces: {
      trace_id: string;
      execution_id: string;
      status: string;
      scenario: string;
    }[];
    next_cursor: string | null;
  }>(`${path}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
  return (
    <>
      {trace && <Detail trace={trace} base={base} query={query} />}
      <ResourceStatus {...r} />
      <Panel title="Executions">
        <div className="panel-body">
          {r.data?.traces.map((t) => (
            <div className="kv" key={t.trace_id}>
              <Link
                className="text-link"
                href={`${base}/traces?trace=${t.trace_id}&${query}`}
              >
                {t.execution_id} · {t.scenario}
              </Link>
              <Badge>{t.status}</Badge>
            </div>
          ))}
          {r.data && !r.data.traces.length && <p>No traces yet.</p>}
          {r.data?.next_cursor && (
            <button
              className="button"
              onClick={() => setCursor(r.data!.next_cursor!)}
            >
              Next page
            </button>
          )}
          {cursor && (
            <button className="button" onClick={() => setCursor("")}>
              First page
            </button>
          )}
        </div>
      </Panel>
    </>
  );
}
