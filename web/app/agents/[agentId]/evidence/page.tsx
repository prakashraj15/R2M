"use client";
import Link from "next/link";
import { Download, FileCheck2 } from "lucide-react";
import { useMock } from "@/components/MockProvider";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
import { Button } from "@/components/ui/button";
import { downloadJSON } from "@/lib/format";
export default function Page() {
  const { state } = useMock();
  function exportEvidence() {
    downloadJSON("r2m-opspilot-demo-evidence.json", {
      schema_version: 1,
      provenance: "frontend_simulation",
      signed: false,
      organization: "Meridian Financial",
      agent: "OpsPilot",
      approvals: state.approvals,
      builds: state.builds,
      executions: state.runs,
      audit: state.audit,
    });
  }
  return (
    <>
      <PageHeader
        eyebrow="OpsPilot / Responsibility record"
        title="Evidence library"
        description="Connect the policy, reviewer, build, execution, and outcome."
        actions={
          <Button variant="default" onClick={exportEvidence}>
            <Download size={15} /> Export demo evidence
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
        subtitle="In-memory mock records; export is unsigned"
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
                    <Badge tone="gray">Simulated</Badge>
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
                    <Badge tone="gray">Simulated</Badge>
                  </td>
                  <td>
                    <Link
                      className="text-link"
                      href={`/agents/opspilot/traces?trace=${r.traceId}`}
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
      <div className="soft-note section-gap">
        This export demonstrates evidence linkage. It is not signed, immutable
        storage, a deployment attestation, or compliance certification. Browser
        refresh resets these records.
      </div>
    </>
  );
}
