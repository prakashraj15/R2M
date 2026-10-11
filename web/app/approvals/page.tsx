"use client";
import { Suspense, useState, useRef } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { useLive, errorText } from "@/components/live/LiveProvider";
import { useResource, ResourceStatus } from "@/components/live/useResource";
import type { LiveApproval } from "@/lib/live-types";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
function ApprovalCard({
  item,
  highlight,
  reload,
}: {
  item: LiveApproval;
  highlight: boolean;
  reload: () => Promise<void>;
}) {
  const live = useLive();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  async function decide(decision: "approve" | "reject") {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await api.decision(item.id, decision, reason);
      await Promise.all([reload(), live.refresh()]);
    } catch (e) {
      setError(errorText(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <div
      className={highlight ? "approval-highlight" : ""}
      id={`approval-${item.id}`}
    >
      <Panel
        title={item.tool_key || item.policy_key || "Policy review"}
        subtitle={`${item.kind} · ${item.id}`}
        action={<Badge>{item.status}</Badge>}
      >
        <div className="panel-body">
          <p>{item.description}</p>
          {item.arguments && (
            <pre>{JSON.stringify(item.arguments, null, 2)}</pre>
          )}
          {item.arguments_hash && (
            <p className="reason-code">Arguments hash: {item.arguments_hash}</p>
          )}
          {item.expires_at && (
            <p>Expires: {new Date(item.expires_at).toLocaleString()}</p>
          )}
          {item.can_decide && (
            <>
              <label className="field-label" htmlFor={`reason-${item.id}`}>
                Decision reason
              </label>
              <textarea
                id={`reason-${item.id}`}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                disabled={busy}
              />
              <div className="button-row">
                <button
                  className="button button-primary"
                  disabled={busy || !reason.trim()}
                  onClick={() => decide("approve")}
                >
                  Approve
                </button>
                <button
                  className="button"
                  disabled={busy || !reason.trim()}
                  onClick={() => decide("reject")}
                >
                  Reject
                </button>
              </div>
            </>
          )}
          {!item.can_decide && item.status === "pending" && (
            <p className="helper">
              This identity cannot decide this request. Choose the authorized
              security reviewer.
            </p>
          )}
          {error && <p role="alert">{error}</p>}
          {item.kind === "runtime_action" && (
            <p className="soft-note">
              After approval, return to OpsPilot and send Continue. The backend
              decides whether execution can resume.
            </p>
          )}
          {item.trace_id && item.agent_id && (
            <Link
              className="text-link"
              href={`/agents/${item.agent_id}/traces?trace=${item.trace_id}&installation_id=${item.installation_id || ""}`}
            >
              Open execution trace →
            </Link>
          )}
        </div>
      </Panel>
    </div>
  );
}
function Queue() {
  const params = useSearchParams();
  const target = params.get("approval");
  const [kind, setKind] = useState<"policy" | "runtime_action">(
    target ? "runtime_action" : "policy",
  );
  const r = useResource<{ approvals: LiveApproval[] }>("/approvals");
  const items = r.data?.approvals.filter((a) => a.kind === kind) || [];
  return (
    <>
      <PageHeader
        eyebrow="Connected control plane"
        title="Approvals"
        description="Policy publication and exact-action decisions come from the backend."
        actions={
          <button className="button" disabled={r.loading} onClick={r.reload}>
            Refresh queue
          </button>
        }
      />
      <div className="tabs">
        <button
          className={kind === "policy" ? "selected" : ""}
          onClick={() => setKind("policy")}
        >
          Policy revisions
        </button>
        <button
          className={kind === "runtime_action" ? "selected" : ""}
          onClick={() => setKind("runtime_action")}
        >
          Operational actions
        </button>
      </div>
      <ResourceStatus {...r} />
      <div className="approval-grid">
        {items.map((item) => (
          <ApprovalCard
            key={item.id}
            item={item}
            highlight={item.id === target}
            reload={r.reload}
          />
        ))}
      </div>
      {r.data && !items.length && (
        <p className="soft-note">No requests in this queue.</p>
      )}
    </>
  );
}
export default function Page() {
  return (
    <Suspense fallback={<p>Loading approvals…</p>}>
      <Queue />
    </Suspense>
  );
}
