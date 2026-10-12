"use client";
import { LogOut } from "lucide-react";
import { useR2M } from "@/components/R2MProvider";
import { roleNames } from "@/lib/permissions";
/** The signed-in account (from the server) and sign out. Switching roles means signing in as another account. */
export function AccountMenu() {
  const { user, role, signOut } = useR2M();
  if (!user) return null;
  return (
    <div className="account-menu">
      <div className="account-id">
        <strong>{user.name}</strong>
        <small>
          {roleNames[role]} · {user.organization}
        </small>
      </div>
      <button className="account-signout" onClick={signOut} aria-label="Sign out">
        <LogOut size={14} /> <span>Sign out</span>
      </button>
    </div>
  );
}
