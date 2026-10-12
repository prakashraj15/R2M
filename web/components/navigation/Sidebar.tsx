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
const agent = "/agents/opspilot";
const links = [
  ["Architecture", agent, Workflow],
  ["Models", agent + "/models", Boxes],
  ["Tools", agent + "/tools", Wrench],
  ["Orchestration", agent + "/orchestration", GitBranch],
  ["Memory & storage", agent + "/storage", Database],
  ["Compute", agent + "/compute", Cpu],
  ["Policies", agent + "/policies", ShieldCheck],
  ["Build evaluations", agent + "/evaluations", ListChecks],
  ["Observability", agent + "/traces", Activity],
  ["Security", agent + "/security", ShieldAlert],
  ["Costs", agent + "/costs", ChartNoAxesCombined],
  ["Evidence", agent + "/evidence", FileCheck2],
] as const;
export function Sidebar() {
  const path = usePathname();
  const { state, role, user } = useR2M();
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
      <div className="nav-label">OPSPILOT WORKSPACE</div>
      <nav aria-label="Agent navigation">
        {links.map(([name, href, Icon]) => (
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
          <span>Open OpsPilot desk</span>
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
