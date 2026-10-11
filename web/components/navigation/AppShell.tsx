"use client";
import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeft, FlaskConical } from "lucide-react";
import { Sidebar } from "./Sidebar";
import { RoleSwitcher } from "./RoleSwitcher";
import { OrgSwitcher } from "./OrgSwitcher";
import { MockDemoGuide } from "@/components/demo/MockDemoGuide";
import { LiveShell } from "@/components/live/LiveShell";
import { BrandMark } from "@/components/brand/BrandMark";
export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  if (path === "/session" || path === "/live") return <>{children}</>;
  if (
    path.startsWith("/demo/") ||
    path === "/approvals" ||
    /^\/agents\/(?!opspilot(?:\/|$))/.test(path)
  )
    return <LiveShell>{children}</LiveShell>;
  const demo = path.startsWith("/demo");
  return (
    <div className={demo ? "demo-shell" : "app-shell"}>
      {!demo && <Sidebar />}
      <div className="main-shell">
        <header className="topbar">
          {demo ? (
            <Link href="/" className="back-link">
              <ArrowLeft size={15} /> <BrandMark /> Control plane
            </Link>
          ) : (
            <div className="breadcrumb">
              Workspace <span>/</span>{" "}
              <strong>
                {path === "/"
                  ? "Organization overview"
                  : path === "/approvals"
                    ? "Review center"
                    : "OpsPilot"}
              </strong>
            </div>
          )}
          <div className="top-actions">
            <Link href="/live" className="button button-primary">
              Live dashboard
            </Link>
            <Link href="/session" className="text-link">
              Backend session
            </Link>
            {demo && <OrgSwitcher />}
            <RoleSwitcher />
            <span className="mock-label">
              <FlaskConical size={12} /> FRONTEND MOCK
            </span>
          </div>
        </header>
        <div className="mock-strip">
          Demo authentication, not production. <span>·</span> Simulated data &
          identities <span>·</span> Changes last until refresh
        </div>
        <main>
          <MockDemoGuide />
          {children}
        </main>
        <footer>
          R2M control plane{" "}
          <span>Local prototype · Demo permissions are not authentication</span>
        </footer>
      </div>
    </div>
  );
}
