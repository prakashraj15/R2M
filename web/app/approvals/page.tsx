"use client";
import { useState } from "react";
import { useR2M } from "@/components/R2MProvider";
import { PageHeader, Empty, Panel, Badge } from "@/components/ui/shared";
import { ApprovalPanel } from "@/components/policy/ApprovalPanel";
export default function Page() {
  const { state } = useR2M();
  const [kind, setKind] = useState<"policy" | "action">(() =>
    state.approvals.some((a) => a.kind === "action" && a.status === "pending")
      ? "action"
      : "policy",
  );
  const [filter, setFilter] = useState("all");
  const items = state.approvals.filter(
    (a) => a.kind === kind && (filter === "all" || a.status === filter),
  );
  return (
    <>
      <PageHeader
        eyebrow="Organization / Review center"
        title="Approvals"
        description="Approve the rule separately from the action. Every decision has an owner."
      />
      <div className="filter-row">
        <div className="tabs">
          <button
            className={kind === "policy" ? "selected" : ""}
            onClick={() => setKind("policy")}
          >
            Policy revisions{" "}
            <b>
              {
                state.approvals.filter(
                  (a) => a.kind === "policy" && a.status === "pending",
                ).length
              }
            </b>
          </button>
          <button
            className={kind === "action" ? "selected" : ""}
            onClick={() => setKind("action")}
          >
            Operational actions{" "}
            <b>
              {
                state.approvals.filter(
                  (a) => a.kind === "action" && a.status === "pending",
                ).length
              }
            </b>
          </button>
        </div>
        <select
          aria-label="Filter approvals by status"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">All statuses</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>
      <div className="approval-grid">
        {items.map((a) => (
          <ApprovalPanel key={a.id} approval={a} />
        ))}
      </div>
      {!items.length && (
        <Panel title="Review queue">
          <Empty
            title="No matching requests"
            description="Exact-action requests appear here when the agent proposes a change that a policy says needs approval (for example a rollback from the operations desk)."
          />
        </Panel>
      )}
      <div className="section-gap">
        <Panel
          title="Decision history"
          action={<Badge tone="gray">Live</Badge>}
        >
          <div className="event-list">
            {state.audit.map((e) => (
              <div key={e.id}>
                <span className="event-dot" />
                <div>
                  <strong>{e.title}</strong>
                  <p>{e.detail}</p>
                </div>
                <small>{new Date(e.at).toLocaleString()}</small>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}
