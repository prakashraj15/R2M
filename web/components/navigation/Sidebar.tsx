"use client";
import Link from "next/link";
import { motion } from "framer-motion";
import { DESK_URL } from "@/lib/live-adapter";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Workflow,
  Boxes,
  Wrench,
  GitBranch,
  Database,
  Cpu,
  ShieldCheck,
  ListChecks,
  Activity,
  ShieldAlert,
  ChartNoAxesCombined,
  FileCheck2,
  Inbox,
  ArrowUpRight,
  PlugZap,
  Building2,
} from "lucide-react";
import { roleNames } from "@/lib/permissions";
import { BrandMark } from "@/components/brand/BrandMark";
import { useR2M } from "@/components/R2MProvider";
// Paths under the agent's workspace (/agents/<registered slug>).
const links = [
  ["Architecture", "", Workflow],
  ["Models", "/models", Boxes],
  ["Tools", "/tools", Wrench],
  ["Orchestration", "/orchestration", GitBranch],
  ["Memory & storage", "/storage", Database],
  ["Compute", "/compute", Cpu],
  ["Policies", "/policies", ShieldCheck],
  ["Build evaluations", "/evaluations", ListChecks],
  ["Observability", "/traces", Activity],
  ["Security", "/security", ShieldAlert],
  ["Costs", "/costs", ChartNoAxesCombined],
  ["Evidence", "/evidence", FileCheck2],
] as const;
export function Sidebar() {
  const path = usePathname();
  const { state, role, user, base } = useR2M();
  const initials = (user?.organization ?? "").split(" ").map((w) => w[0]).join("").slice(0, 2);
  const count = state.approvals.filter((a) => a.status === "pending").length;
  return (
    <aside className="sidebar">
      <Link className="brand" href="/" aria-label="R2M home">
        <BrandMark />
        <span className="beta">BETA</span>
      </Link>
      <div className="brand-caption">RESPONSIBILITY TO MONITORING</div>
      <div className="org-switch" title="Your organization">
        <Building2 size={17} />
        <span>{user?.organization ?? "…"}</span>
      </div>
      <div className="nav-label">CONTROL PLANE</div>
      <nav aria-label="Organization navigation">
        <Link className={path === "/" ? "active" : ""} href="/">
          {path === "/" && <motion.span layoutId="nav-active" className="nav-pill" />}
          <LayoutDashboard size={16} />
          <span>Overview</span>
        </Link>
        <Link
          className={path === "/approvals" ? "active" : ""}
          href="/approvals"
        >
          {path === "/approvals" && <motion.span layoutId="nav-active" className="nav-pill" />}
          <Inbox size={16} />
          <span>Approvals</span>
          {count > 0 && <b>{count}</b>}
        </Link>
      </nav>
      <div className="nav-label">{(state.identity.agent || "Agent").toUpperCase()} WORKSPACE</div>
      <nav aria-label="Agent navigation">
        {links.map(([name, sub, Icon]) => [name, base + sub, Icon] as const).map(([name, href, Icon]) => (
          <Link
            className={path === href ? "active" : ""}
            href={href}
            key={href}
          >
            {path === href && <motion.span layoutId="nav-active" className="nav-pill" />}
            <Icon size={16} />
            <span>{name}</span>
          </Link>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <a className="demo-link" href={DESK_URL}>
          <PlugZap size={17} />
          <span>Open {state.identity.agent || "agent"} desk</span>
          <ArrowUpRight size={14} />
        </a>
        <div className="profile">
          <div className="avatar">{initials}</div>
          <div>
            {user?.name ?? "…"}
            <small>{roleNames[role]}</small>
          </div>
        </div>
      </div>
    </aside>
  );
}
