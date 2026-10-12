"use client";
import { useState } from "react";
import Link from "next/link";
import type { Approval } from "@/lib/types";
import { useR2M } from "@/components/R2MProvider";
import { canReview } from "@/lib/permissions";
import { Button } from "@/components/ui/button";
import { Badge, Panel } from "@/components/ui/shared";
export function ApprovalPanel({ approval }: { approval: Approval }) {
  const [reason, setReason] = useState("");
  // One decision per click: locked until the refreshed approval arrives (a new id or status re-keys this state).
  const [sentFor, setSentFor] = useState("");
  const busy = sentFor === `${approval.id}:${approval.status}`;
  const { state, role, dispatch, base } = useR2M();
  const { identity } = state;
  const run = state.runs.find((r) => r.id === approval.executionId);
  const policyReady =
    approval.kind === "policy" ||
    state.approvals.some(
      (a) =>
        a.kind === "policy" &&
        a.policy === approval.policy &&
        a.status === "approved",
    );
  return (
    <Panel
      title={approval.subject}
      subtitle={`${approval.kind === "policy" ? "Policy publication" : "Exact-action"} review · ${approval.id}`}
      action={<Badge>{approval.status}</Badge>}
    >
      <div className="panel-body">
        <p className="body-copy">{approval.description}</p>
        <div className="kv">
          <span>Requested by</span>
          <strong>{approval.requestedBy}</strong>
        </div>
        <div className="kv">
          <span>Governing policy</span>
          <strong>{approval.policy}</strong>
        </div>
        <div className="field-label">BOUND REVISION / ACTION DIGEST (SHA-256)</div>
        <pre>{approval.digest}</pre>
        {approval.kind === "action" && (
          <div className="soft-note">
            One action only. This approval does not grant ongoing tool access.
            The governing policy must be approved first.
          </div>
        )}
        {approval.status === "pending" ? (
          <>
            <label className="field-label" htmlFor={`reason-${approval.id}`}>
              REVIEW REASON
            </label>
            <textarea
              id={`reason-${approval.id}`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Explain why this scope is approved or rejected…"
              disabled={!canReview(role)}
            />
            <div className="button-row">
              <Button
                variant="default"
                disabled={busy || !canReview(role) || approval.canDecide === false || !reason.trim() || !policyReady}
                onClick={() => {
                  setSentFor(`${approval.id}:${approval.status}`);
                  dispatch({
                    type: "review",
                    id: approval.id,
                    decision: "approved",
                    reason,
                  });
                }}
              >
                Approve
              </Button>
              <Button
                disabled={busy || !canReview(role) || approval.canDecide === false || !reason.trim()}
                onClick={() => {
                  setSentFor(`${approval.id}:${approval.status}`);
                  dispatch({
                    type: "review",
                    id: approval.id,
                    decision: "rejected",
                    reason,
                  });
                }}
              >
                Reject
              </Button>
            </div>
            {!canReview(role) && (
              <p className="helper">
                Only a security reviewer of {identity.customer} can decide. Sign in
                with that account.
              </p>
            )}
            {!policyReady && (
              <p className="helper">
                Approval is unavailable until the governing policy revision is
                approved. You can still reject this action.
              </p>
            )}
          </>
        ) : (
          <div className="soft-note">
            {approval.reviewedBy} ·{" "}
            {approval.reason || "No reason recorded."}
          </div>
        )}
        {run && (
          <Link
            className="text-link"
            href={`${base}/traces?trace=${run.traceId}`}
          >
            View associated execution →
          </Link>
        )}
      </div>
    </Panel>
  );
}
