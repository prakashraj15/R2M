"use client";
import Link from "next/link";
import type { Policy } from "@/lib/types";
import { useMock } from "@/components/MockProvider";
import { Panel, Badge } from "@/components/ui/shared";
export function PolicyDetail({ policy }: { policy: Policy }) {
  const { state } = useMock();
  const review = state.approvals.find(
    (a) => a.kind === "policy" && a.policy === policy.id,
  );
  return (
    <Panel
      title={policy.name}
      subtitle={`${policy.id} · v${policy.version}`}
      action={<Badge>{review?.status || "Unknown"}</Badge>}
    >
      <div className="panel-body">
        <p className="body-copy">{policy.description}</p>
        <div className="detail-grid">
          <div>
            <div className="field-label">OWNER</div>
            <strong>{policy.owner}</strong>
          </div>
          <div>
            <div className="field-label">ENFORCEMENT HOOK</div>
            <strong>{policy.hook}</strong>
          </div>
          <div>
            <div className="field-label">REQUESTED PERMISSION</div>
            <strong>{policy.permission}</strong>
          </div>
          <div>
            <div className="field-label">APPROVED DEPLOYMENT SCOPE</div>
            <strong>
              OpsPilot · Meridian Financial · production simulation
            </strong>
          </div>
        </div>
        <div className="field-label">CODE ARTIFACT DIGEST · ILLUSTRATIVE</div>
        <pre>{policy.hash}</pre>
        <div className="soft-note">
          Policies are defined in agent code. The dashboard reviews metadata and
          exact revisions; it does not edit executable rules.
        </div>
        <div className="link-row">
          <Link href="/approvals" className="text-link">
            Review history & decisions →
          </Link>
          <Link href="/agents/opspilot/evaluations" className="text-link">
            Related build checks →
          </Link>
          <Link href="/agents/opspilot/evidence" className="text-link">
            Linked evidence →
          </Link>
        </div>
      </div>
    </Panel>
  );
}
