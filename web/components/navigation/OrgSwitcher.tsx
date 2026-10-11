"use client";
import { Building2 } from "lucide-react";
import { useMock } from "@/components/MockProvider";
import type { Organization } from "@/lib/types";
export function OrgSwitcher() {
  const { org, setOrg } = useMock();
  return (
    <div className="org-switch">
      <Building2 size={17} />
      <select
        aria-label="Organization perspective"
        value={org}
        onChange={(e) => setOrg(e.target.value as Organization)}
      >
        <option value="atlas">Atlas Applied AI</option>
        <option value="meridian">Meridian Financial</option>
      </select>
    </div>
  );
}
