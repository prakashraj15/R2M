"use client";
import { usePathname, useSearchParams } from "next/navigation";
import { useLive } from "./LiveProvider";
import { useResource, ResourceStatus } from "./useResource";
import { LiveTopology } from "./LiveTopology";
import { LiveTraces } from "./LiveTraces";
import {
  LivePolicies,
  LiveEvaluations,
  LiveSecurity,
  LiveEvidence,
} from "./LiveModules";
import { PageHeader, Panel } from "@/components/ui/shared";
import { metric } from "@/lib/live-types";
function Costs({ path }: { path: string }) {
  const r = useResource<{
    summary: {
      run_success: { value: number | null };
      policy_enforcement_coverage: {
        value: number | null;
        explanation: string;
      };
      p95_action_latency_ms: number | null;
      cost: { by_source: Record<string, number>; provenance_note: string };
    };
    series: {
      cost: { bucket: string; cost_source: string; usd: number }[];
      latency: { bucket: string; p95_ms: number | null }[];
    };
  }>(path);
  const s = r.data?.summary;
  return (
    <>
      <ResourceStatus {...r} />
      {s && (
        <>
          <Panel title="Cost provenance">
            <div className="panel-body">
              {Object.entries(s.cost.by_source).map(([source, value]) => (
                <p key={source}>
                  <strong>{source}</strong>: ${value}{" "}
                  {source === "estimated"
                    ? "· list-price estimate, not an invoice"
                    : source === "simulated"
                      ? "· simulated model usage"
                      : ""}
                </p>
              ))}
              <p className="helper">{s.cost.provenance_note}</p>
            </div>
          </Panel>
          <Panel title="Performance & observed coverage">
            <div className="panel-body">
              <p>
                Run success:{" "}
                {metric(
                  s.run_success.value == null
                    ? null
                    : Math.round(s.run_success.value * 10000) / 100,
                  "%",
                )}
              </p>
              <p>P95: {metric(s.p95_action_latency_ms, " ms")}</p>
              <p>
                Observed coverage:{" "}
                {metric(
                  s.policy_enforcement_coverage.value == null
                    ? null
                    : Math.round(s.policy_enforcement_coverage.value * 10000) /
                        100,
                  "%",
                )}
              </p>
              <p className="helper">
                {s.policy_enforcement_coverage.explanation}
              </p>
            </div>
          </Panel>
          <Panel title="Cost over time">
            <div className="panel-body">
              {r.data?.series.cost.map((c, i) => (
                <p key={i}>
                  {c.bucket} · {c.cost_source} · ${c.usd}
                </p>
              ))}
            </div>
          </Panel>
          <Panel title="Latency over time">
            <div className="panel-body">
              {r.data?.series.latency.map((l, i) => (
                <p key={i}>
                  {l.bucket} · {metric(l.p95_ms, " ms")}
                </p>
              ))}
            </div>
          </Panel>
        </>
      )}
    </>
  );
}
export function LiveWorkspace({ agent }: { agent: string }) {
  const params = useSearchParams();
  const pathname = usePathname();
  const live = useLive();
  const base = `/agents/${agent}`;
  const section = pathname.slice(base.length).replace(/^\//, "");
  const installation =
    params.get("installation_id") || live.state?.installation_id;
  const query = `installation_id=${encodeURIComponent(installation || "")}`;
  const path = `${base}/${section}?${query}`;
  if (!installation)
    return (
      <p className="soft-note">
        Load the backend demo installation to open this workspace.
      </p>
    );
  return (
    <>
      <PageHeader
        eyebrow="OpsPilot / Connected workspace"
        title={
          section
            ? section[0].toUpperCase() + section.slice(1)
            : "Runtime topology"
        }
        description="Backend records for the selected installation. Missing telemetry is Unknown."
      />
      {!section ? (
        <LiveTopology path={`${base}/topology?${query}`} />
      ) : section === "traces" ? (
        <LiveTraces
          path={path}
          trace={params.get("trace")}
          base={base}
          query={query}
        />
      ) : section === "policies" ? (
        <LivePolicies path={path} agent={agent} installation={installation} />
      ) : section === "evaluations" ? (
        <LiveEvaluations path={path} agent={agent} query={query} base={base} />
      ) : section === "security" ? (
        <LiveSecurity
          path={`${base}/incidents?${query}`}
          base={base}
          query={query}
        />
      ) : section === "costs" ? (
        <Costs path={`${base}/metrics?${query}`} />
      ) : section === "evidence" ? (
        <LiveEvidence path={path} />
      ) : (
        <LiveTopology path={`${base}/topology?${query}`} />
      )}
    </>
  );
}
