"use client";
import Link from "next/link";
import { Download, FileCheck2 } from "lucide-react";
import { useR2M } from "@/components/R2MProvider";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
import { Button } from "@/components/ui/button";
import { downloadJSON } from "@/lib/format";
import { api } from "@/lib/api";
export default function Page() {
  const { state, agentId, notify, base } = useR2M();
  const { identity } = state;
  // The bundle is built server-side: every item with its SHA-256, plus a manifest hash over the whole bundle.
  async function exportEvidence() {
    try {
      const bundle = await api.exportEvidence(agentId);
      downloadJSON(`r2m-opspilot-evidence-${new Date().toISOString().slice(0, 10)}.json`, bundle);
    } catch (e) {
      notify(e instanceof Error ? e.message : "Export failed.");
    }
  }
  return (
    <>
      <PageHeader
        eyebrow={`${state.identity.agent} / Responsibility record`}
        title="Evidence library"
        description="Connect the policy, reviewer, build, execution, and outcome."
        actions={
          <Button variant="default" onClick={exportEvidence}>
            <Download size={15} /> Export evidence bundle
          </Button>
        }
      />
      <div className="evidence-chain">
        {[
          "Code policy",
          "Build checks",
          "Customer approval",
          "Tool action",
          "Verified outcome",
        ].map((s, i) => (
          <div key={s}>
            <FileCheck2 size={19} />
            <span>
              <small>0{i + 1}</small>
              {s}
            </span>
            {i < 4 && <b>→</b>}
          </div>
        ))}
      </div>
      <Panel
        title="Linked evidence"
        subtitle="Records stored in R2M; each evidence item carries a SHA-256 integrity hash"
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ARTIFACT</th>
                <th>REFERENCE</th>
                <th>PROVENANCE</th>
                <th>OPEN</th>
              </tr>
            </thead>
            <tbody>
              {state.approvals.map((a) => (
                <tr key={a.id}>
                  <td>
                    {a.kind === "policy"
                      ? "Policy revision review"
                      : "Exact-action decision"}
                    <small>{a.subject}</small>
                  </td>
                  <td>{a.id}</td>
                  <td>
                    <Badge tone="green">Recorded</Badge>
                  </td>
                  <td>
                    <Link className="text-link" href="/approvals">
                      Review ↗
                    </Link>
                  </td>
                </tr>
              ))}
              {state.runs.map((r) => (
                <tr key={r.id}>
                  <td>
                    Execution trace<small>{r.scenario}</small>
                  </td>
                  <td>{r.traceId}</td>
                  <td>
                    <Badge tone="green">Recorded</Badge>
                  </td>
                  <td>
                    <Link
                      className="text-link"
                      href={`${base}/traces?trace=${r.traceId}`}
                    >
                      Inspect ↗
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title="Integrity log" subtitle="Evidence written by the platform as approvals, gates and actions happen">
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>EVENT</th><th>INTEGRITY</th><th>RECORDED</th></tr>
            </thead>
            <tbody>
              {state.audit.map((e) => (
                <tr key={e.id}>
                  <td>{e.title}</td>
                  <td>{e.detail}</td>
                  <td>{new Date(e.at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="soft-note section-gap">
        The export is hash-chained to a manifest digest, not cryptographically signed. It is evidence of what R2M
        observed, not a compliance certification.
      </div>
    </>
  );
}
