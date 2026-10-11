"use client";
import { useState, useRef } from "react";
import Link from "next/link";
import { api, request } from "@/lib/api";
import { downloadJSON } from "@/lib/format";
import { useLive, errorText } from "./LiveProvider";
import { useResource, ResourceStatus } from "./useResource";
import { Panel, Badge } from "@/components/ui/shared";
export function Mutation({
  label,
  action,
  after,
}: {
  label: string;
  action: () => Promise<unknown>;
  after?: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  return (
    <>
      <button
        className="button"
        disabled={busy}
        onClick={async () => {
          if (lock.current) return;
          lock.current = true;
          setBusy(true);
          setError("");
          try {
            await action();
            await after?.();
          } catch (e) {
            setError(errorText(e));
          } finally {
            lock.current = false;
            setBusy(false);
          }
        }}
      >
        {busy ? "Working…" : label}
      </button>
      {error && <p role="alert">{error}</p>}
    </>
  );
}
export function LivePolicies({
  path,
  agent,
  installation,
}: {
  path: string;
  agent: string;
  installation: string;
}) {
  const live = useLive();
  const r = useResource<{
    policies: {
      id: string;
      policy_key: string;
      version: string;
      description: string;
      owner_email: string;
      artifact_hash: string;
      coverage_caveat: string;
      submissions: {
        id: string;
        status: string;
        active: boolean;
        history: unknown;
      }[];
      operational_decisions: Record<string, number>;
    }[];
  }>(path);
  return (
    <>
      <ResourceStatus {...r} />
      {r.data?.policies.map((p) => (
        <Panel
          key={p.id}
          title={`${p.policy_key} · ${p.version}`}
          subtitle={p.owner_email}
        >
          <div className="panel-body">
            <p>{p.description}</p>
            <code className="reason-code">{p.artifact_hash}</code>
            <p className="helper">{p.coverage_caveat}</p>
            <p>Runtime decisions: {JSON.stringify(p.operational_decisions)}</p>
            {p.submissions.map((s) => (
              <details key={s.id}>
                <summary>
                  {s.status} · {s.active ? "Active" : "Inactive"}
                </summary>
                <pre>{JSON.stringify(s.history, null, 2)}</pre>
              </details>
            ))}
            {live.can("policy.submit") && (
              <Mutation
                label="Submit revision for approval"
                action={() => api.submitPolicy(agent, p.id, installation)}
                after={r.reload}
              />
            )}
          </div>
        </Panel>
      ))}
      {r.data && !r.data.policies.length && <p>No registered policies.</p>}
    </>
  );
}
interface Deployment {
  id: string;
  version: string;
  status: string;
  artifact_digest: string;
  installation_id: string;
}
interface ReleaseResult {
  deployment_id: string;
  status: string;
  eligible: boolean;
  checks: Record<string, boolean>;
  details: unknown;
}
function ReleaseCard({
  d,
  agent,
  reload,
}: {
  d: Deployment;
  agent: string;
  reload: () => Promise<void>;
}) {
  const live = useLive();
  const [result, setResult] = useState<ReleaseResult | null>(null);
  return (
    <Panel title={d.version} action={<Badge>{d.status}</Badge>}>
      <div className="panel-body">
        <code className="reason-code">{d.artifact_digest}</code>
        {live.can("release.evaluate") && (
          <Mutation
            label="Evaluate release"
            action={async () => {
              setResult(null);
              setResult(
                await request<ReleaseResult>(
                  `/agents/${agent}/releases/evaluate`,
                  {
                    method: "POST",
                    body: JSON.stringify({
                      installation_id: d.installation_id,
                      build_version: d.version,
                      artifact_digest: d.artifact_digest,
                    }),
                  },
                ),
              );
            }}
          />
        )}
        {result && (
          <>
            <Badge>{result.status}</Badge>
            {Object.entries(result.checks).map(([k, v]) => (
              <p key={k}>
                {v ? "✓" : "×"} {k.replaceAll("_", " ")}
              </p>
            ))}
            <details>
              <summary>Gate details</summary>
              <pre>{JSON.stringify(result.details, null, 2)}</pre>
            </details>
            {result.eligible &&
              live.can("release.deploy") &&
              d.status !== "deployed" && (
                <Mutation
                  label="Deploy evaluated build"
                  action={() => api.deploy(agent, result.deployment_id)}
                  after={async () => {
                    setResult(null);
                    await reload();
                    await live.refresh();
                  }}
                />
              )}
          </>
        )}
      </div>
    </Panel>
  );
}
export function LiveEvaluations({
  path,
  agent,
  query,
  base,
}: {
  path: string;
  agent: string;
  query: string;
  base: string;
}) {
  const r = useResource<{
    runs: {
      id: string;
      version: string;
      suite_key: string;
      status: string;
      mandatory_failure: boolean;
      cases: {
        id: string;
        case_key: string;
        status: string;
        mandatory: boolean;
        expected: unknown;
        actual: unknown;
        trace_id: string | null;
      }[];
    }[];
  }>(path);
  const d = useResource<{ deployments: Deployment[] }>(
    `/agents/${agent}/deployments?${query}`,
  );
  return (
    <>
      <p className="soft-note">
        Evaluations are published by CI. The browser evaluates release
        eligibility and deploys; it does not run the suites.
      </p>
      <ResourceStatus {...d} />
      <div className="two-column">
        {d.data?.deployments.map((item) => (
          <ReleaseCard key={item.id} d={item} agent={agent} reload={d.reload} />
        ))}
      </div>
      <ResourceStatus {...r} />
      {r.data?.runs.map((run) => (
        <Panel
          key={run.id}
          title={`${run.version} · ${run.suite_key}`}
          action={
            <Badge tone={run.mandatory_failure ? "red" : undefined}>
              {run.status}
            </Badge>
          }
        >
          <div className="panel-body">
            {run.cases.map((c) => (
              <details key={c.id}>
                <summary>
                  {c.case_key} · {c.status} {c.mandatory ? "· mandatory" : ""}
                </summary>
                <pre>
                  {JSON.stringify(
                    { expected: c.expected, actual: c.actual },
                    null,
                    2,
                  )}
                </pre>
                {c.trace_id && (
                  <Link
                    className="text-link"
                    href={`${base}/traces?trace=${c.trace_id}&${query}`}
                  >
                    Open trace →
                  </Link>
                )}
              </details>
            ))}
          </div>
        </Panel>
      ))}
    </>
  );
}
export function LiveSecurity({
  path,
  base,
  query,
}: {
  path: string;
  base: string;
  query: string;
}) {
  const live = useLive();
  const r = useResource<{
    incidents: {
      id: string;
      severity: string;
      status: string;
      incident_type?: string;
      kind?: string;
      title?: string;
      description?: string;
      trace_id: string | null;
    }[];
  }>(path);
  return (
    <>
      <ResourceStatus {...r} />
      {r.data?.incidents.map((i) => (
        <Panel
          key={i.id}
          title={i.title || i.incident_type || i.kind || i.id}
          action={
            <Badge tone={i.severity === "critical" ? "red" : "amber"}>
              {i.severity} · {i.status}
            </Badge>
          }
        >
          <div className="panel-body">
            <p>{i.description}</p>
            {i.trace_id && (
              <Link
                className="text-link"
                href={`${base}/traces?trace=${i.trace_id}&${query}`}
              >
                Open trace →
              </Link>
            )}
            {live.can("incident.manage") && (
              <div className="button-row">
                <Mutation
                  label="Investigate"
                  action={() =>
                    api.updateIncident(
                      i.id,
                      "investigating",
                      "Investigating from R2M UI",
                    )
                  }
                  after={r.reload}
                />
                <Mutation
                  label="Resolve"
                  action={() =>
                    api.updateIncident(i.id, "resolved", "Resolved from R2M UI")
                  }
                  after={r.reload}
                />
              </div>
            )}
          </div>
        </Panel>
      ))}
      {r.data && !r.data.incidents.length && (
        <p className="soft-note">No incidents returned.</p>
      )}
    </>
  );
}
export function LiveEvidence({ path }: { path: string }) {
  const live = useLive();
  const r = useResource<{
    items: {
      id: string;
      kind: string;
      sha256: string;
      integrity_ok: boolean | null;
    }[];
    caveat: string;
  }>(path);
  return (
    <>
      <ResourceStatus {...r} />
      {r.data && (
        <>
          <p className="soft-note">{r.data.caveat}</p>
          {live.can("evidence.export") && (
            <Mutation
              label="Export evidence"
              action={async () =>
                downloadJSON(
                  "r2m-evidence.json",
                  await request(
                    path.replace("/evidence?", "/evidence/export?"),
                  ),
                )
              }
            />
          )}
          {r.data.items.map((e) => (
            <div className="panel panel-body" key={e.id}>
              <strong>{e.kind || e.id}</strong>
              <Badge
                tone={
                  e.integrity_ok === true
                    ? "green"
                    : e.integrity_ok === false
                      ? "red"
                      : "gray"
                }
              >
                {e.integrity_ok === true
                  ? "Integrity verified"
                  : e.integrity_ok === false
                    ? "Integrity mismatch"
                    : "Integrity unknown"}
              </Badge>
              <code className="reason-code">{e.sha256}</code>
            </div>
          ))}
        </>
      )}
    </>
  );
}
