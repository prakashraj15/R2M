"use client";
import { useR2M } from "@/components/R2MProvider";
import { useState } from "react";
import { PageHeader, Panel } from "@/components/ui/shared";
import { PolicyTable } from "@/components/policy/PolicyTable";
import { PolicyDetail } from "@/components/policy/PolicyDetail";
import Link from "next/link";
export default function Page() {
  const { state, policies } = useR2M();
  const [picked, setId] = useState("");
  const id = picked || policies[0]?.id || "";
  return (
    <>
      <PageHeader
        eyebrow={`${state.identity.agent} / Governance`}
        title="Policy control"
        description="Code-owned rules. Explicit responsibility. Version-bound approval."
        actions={
          <Link href="/approvals" className="button button-primary">
            Open approval queue →
          </Link>
        }
      />
      <Panel
        title="Policy inventory"
        subtitle={`${policies.length} registered code artifact${policies.length === 1 ? "" : "s"} · Assigned to ${state.identity.agent}`}
      >
        <PolicyTable selected={id} onSelect={setId} />
      </Panel>
      <div className="section-gap">
        {policies.find((p) => p.id === id) ? (
          <PolicyDetail policy={policies.find((p) => p.id === id)!} />
        ) : (
          <p className="soft-note">Select a policy. Policies appear once the agent registers them.</p>
        )}
      </div>
    </>
  );
}
