"use client";
import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeft, Radio } from "lucide-react";
import { Sidebar } from "./Sidebar";
import { AccountMenu } from "./AccountMenu";
import { BrandMark } from "@/components/brand/BrandMark";
import { APP, CONTROL_URL, DESK_URL } from "@/lib/live-adapter";
import { MotionRoot, PageTransition } from "@/components/ui/motion";
// Two separate apps from one codebase (NEXT_PUBLIC_R2M_APP): the R2M Control Plane and the OpsPilot Operations Desk.
export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  if (path === "/login") return <MotionRoot>{children}</MotionRoot>;
  const desk = APP === "desk";
  return (
    <MotionRoot>
    <div className={desk ? "demo-shell" : "app-shell"}>
      {!desk && <Sidebar />}
      <div className="main-shell">
        <header className="topbar">
          {desk ? (
            <a href={CONTROL_URL} className="back-link">
              <ArrowLeft size={15} /> <BrandMark /> R2M control plane
            </a>
          ) : (
            <div className="breadcrumb">
              Workspace <span>/</span>{" "}
              <strong>
                {path === "/" ? "Organization overview" : path === "/approvals" ? "Review center" : "OpsPilot"}
              </strong>
            </div>
          )}
          <div className="top-actions">
            {!desk && (
              <a href={DESK_URL} className="text-link">
                OpsPilot desk ↗
              </a>
            )}
            <AccountMenu />
            <span className="mock-label">
              <Radio size={12} /> LIVE
            </span>
          </div>
        </header>
        <main>
          <PageTransition id={path}>{children}</PageTransition>
        </main>
        <footer>
          {desk ? "OpsPilot operations desk" : "R2M control plane"}
        </footer>
      </div>
    </div>
    </MotionRoot>
  );
}
