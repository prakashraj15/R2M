"use client";
import { useState } from "react";
import Link from "next/link";
import type { ComponentInfo } from "@/lib/types";
import { Badge } from "@/components/ui/shared";
import { duration } from "@/lib/format";
import { useMock } from "@/components/MockProvider";
export function NodeInspector({ component }: { component: ComponentInfo }) {
  const [tab, setTab] = useState("Metrics");
  const { state } = useMock();
  return (
    <aside className="panel inspector">
      <div className="panel-heading">
        <h2>Component inspector</h2>
        <span className="tiny muted">{component.kind}</span>
      </div>
      <div className="inspector-body">
        <div className="eyebrow">OPSPILOT / {component.id}</div>
        <h3>{component.name}</h3>
        <Badge>{component.health}</Badge>
        <p>{component.description}</p>
        <div className="tabs">
          {["Metrics", "Events", "Policies", "Configuration"].map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={tab === t ? "selected" : ""}
            >
              {t}
            </button>
          ))}
        </div>
        {tab === "Metrics" ? (
          <>
            <div className="kv">
              <span>Calls</span>
              <strong>{component.calls ?? "Unknown"}</strong>
            </div>
            <div className="kv">
              <span>Errors</span>
              <strong>{component.errors ?? "Unknown"}</strong>
            </div>
            <div className="kv">
              <span>P95 latency</span>
              <strong>
                {component.latency ? duration(component.latency) : "Unknown"}
              </strong>
            </div>
            <div className="kv">
              <span>Source</span>
              <strong>Simulated fixture</strong>
            </div>
            <div className="soft-note">
              Metrics describe the design fixture, not a live SDK connection.
            </div>
          </>
        ) : tab === "Events" ? (
          <div className="compact-events">
            {state.runs.slice(0, 3).map((r) => (
              <Link
                href={`/agents/opspilot/traces?trace=${r.traceId}`}
                key={r.id}
              >
                <strong>{r.id}</strong>
                <small>{r.status.replaceAll("_", " ")} →</small>
              </Link>
            ))}
          </div>
        ) : tab === "Policies" ? (
          <>
            <Link className="text-link" href="/agents/opspilot/policies">
              DEPLOY-001 · Rollback approval ↗
            </Link>
            <p>
              Policies bind to named tool boundaries. Scope is not inferred from
              a green node.
            </p>
          </>
        ) : (
          <pre>
            {JSON.stringify(
              {
                component: component.id,
                environment: "production simulation",
                instrumentation: "mock",
                payload_capture: false,
              },
              null,
              2,
            )}
          </pre>
        )}
      </div>
    </aside>
  );
}
