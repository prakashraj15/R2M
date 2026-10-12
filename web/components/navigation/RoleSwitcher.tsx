"use client";
import { useR2M } from "@/components/R2MProvider";
import { roleNames, rolesFor } from "@/lib/permissions";
import type { Role } from "@/lib/types";
export function RoleSwitcher() {
  const { role, org, setRole } = useR2M();
  return (
    <select
      className="role-select"
      aria-label="Signed-in role"
      value={role}
      onChange={(e) => setRole(e.target.value as Role)}
    >
      {rolesFor[org].map((r) => (
        <option key={r} value={r}>
          {roleNames[r]}
        </option>
      ))}
    </select>
  );
}
