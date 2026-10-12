"use client";
import { useState } from "react";
import Link from "next/link";
import type { ComponentInfo } from "@/lib/types";
import { Badge } from "@/components/ui/shared";
import { duration } from "@/lib/format";
import { useR2M } from "@/components/R2MProvider";
export function NodeInspector({ component }: { component: ComponentInfo }) {
  const [tab, setTab] = useState("Metrics");
  const { state, policies, base } = useR2M();
  const { identity } = state;
  const binding = ["tools", "gateway"].includes(component.id) ? policies : [];
  return (
    <aside className="panel inspector">
      <div className="panel-heading">
        <h2>Component inspector</h2>
        <span className="tiny muted">{component.kind}</span>
      </div>
      <div className="inspector-body">
        <div className="eyebrow">{identity.agent.toUpperCase()} / {component.id}</div>
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
              <strong>Live telemetry</strong>
            </div>
            <div className="soft-note">
              Metrics come from SDK spans in the last 24 h; missing telemetry is Unknown.
            </div>
          </>
        ) : tab === "Events" ? (
          <div className="compact-events">
            {state.runs.slice(0, 3).map((r) => (
              <Link
                href={`${base}/traces?trace=${r.traceId}`}
                key={r.id}
              >
                <strong>{r.id}</strong>
                <small>{r.status.replaceAll("_", " ")} →</small>
              </Link>
            ))}
          </div>
        ) : tab === "Policies" ? (
          <>
            {binding.map((p) => (
              <Link className="text-link" href={`${base}/policies`} key={p.id}>
                {p.id} · {p.permission} · {p.tool} ↗
              </Link>
            ))}
            <p>
              {binding.length
                ? "Policies bind to named tool boundaries and are enforced at the policy gate."
                : "No policy binds directly to this component."}{" "}
              Scope is not inferred from a green node.
            </p>
          </>
        ) : (
          <pre>
            {JSON.stringify(
              {
                component: component.id,
                kind: component.kind,
                members: component.description,
                environment: "production",
                instrumentation: "r2m-sdk",
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
