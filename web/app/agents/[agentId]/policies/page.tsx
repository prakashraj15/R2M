"use client";
import { useState } from "react";
import { PageHeader, Panel } from "@/components/ui/shared";
import { PolicyTable } from "@/components/policy/PolicyTable";
import { PolicyDetail } from "@/components/policy/PolicyDetail";
import { policies } from "@/lib/mock-data";
import Link from "next/link";
export default function Page() {
  const [id, setId] = useState("DEPLOY-001");
  return (
    <>
      <PageHeader
        eyebrow="OpsPilot / Governance"
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
        subtitle="3 registered code artifacts · Assigned to OpsPilot"
      >
        <PolicyTable selected={id} onSelect={setId} />
      </Panel>
      <div className="section-gap">
        <PolicyDetail policy={policies.find((p) => p.id === id)!} />
      </div>
    </>
  );
}
