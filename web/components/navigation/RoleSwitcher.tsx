"use client";
import { useMock } from "@/components/MockProvider";
import { roleNames, rolesFor } from "@/lib/permissions";
import type { Role } from "@/lib/types";
export function RoleSwitcher() {
  const { role, org, setRole } = useMock();
  return (
    <select
      className="role-select"
      aria-label="Demo role"
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
