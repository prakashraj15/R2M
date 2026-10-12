"use client";
import Link from "next/link";
import type { Policy } from "@/lib/types";
import { useR2M } from "@/components/R2MProvider";
import { Panel, Badge } from "@/components/ui/shared";
export function PolicyDetail({ policy }: { policy: Policy }) {
  const { state, role, dispatch, base } = useR2M();
  const { identity } = state;
  // The approval currently in force for this policy (the one a revoke would withdraw).
  const review = state.approvals.find(
    (a) => a.kind === "policy" && a.policy === policy.id && a.status === "approved",
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
            <div className="field-label">APPROVAL STATE</div>
            <strong>
              v{policy.version} · {policy.permission}
              {policy.activeVersion && ` (v${policy.activeVersion} still in force)`}
            </strong>
          </div>
          <div>
            <div className="field-label">GOVERNED TOOLS · SCOPE</div>
            <strong>
              {policy.tool || "—"} · {identity.agent} · {identity.customer} · {identity.environment}
            </strong>
          </div>
        </div>
        <div className="field-label">CODE ARTIFACT DIGEST (SHA-256 of the policy source)</div>
        <pre>{policy.hash}</pre>
        <div className="soft-note">
          Policies are defined in agent code. The dashboard reviews metadata and
          exact revisions; it does not edit executable rules.
        </div>
        {role === "vendor_developer" && policy.canSubmit && (
          <button className="button button-primary" onClick={() => dispatch({ type: "submitPolicy", id: policy.revisionId })}>
            Submit v{policy.version} for {identity.customer} review
          </button>
        )}
        {role === "customer_security" && review && policy.permission === "Approved" && (
          <button
            className="button"
            onClick={() => dispatch({ type: "revoke", id: review.id, reason: "Revoked from the policy workspace" })}
          >
            Revoke approval (takes effect on the next action)
          </button>
        )}
        <div className="link-row">
          <Link href="/approvals" className="text-link">
            Review history & decisions →
          </Link>
          <Link href={`${base}/evaluations`} className="text-link">
            Related build checks →
          </Link>
          <Link href={`${base}/evidence`} className="text-link">
            Linked evidence →
          </Link>
        </div>
      </div>
    </Panel>
  );
}
