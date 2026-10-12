"use client";
import type { ReactNode } from "react";
import { motion, rise } from "./motion";
import { ArrowUpRight, FlaskConical } from "lucide-react";
export function Badge({
  children,
  tone,
}: {
  children: ReactNode;
  tone?: string;
}) {
  const text = String(children).toLowerCase();
  const t =
    tone ||
    (/fail|critical|reject|blocked/.test(text)
      ? "red"
      : /pending|waiting|degraded|review/.test(text)
        ? "amber"
        : /unknown|disabled|not |unavailable/.test(text)
          ? "gray"
          : "green");
  return (
    <span className={`badge ${t}`}>
      <i />
      {children}
    </span>
  );
}
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="header-actions">{actions}</div>
    </div>
  );
}
export function Panel({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.section className={`panel ${className}`} variants={rise} initial="hidden" animate="show">
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </motion.section>
  );
}
export function Empty({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="empty">
      <FlaskConical size={30} />
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  );
}
export function Arrow() {
  return <ArrowUpRight size={14} />;
}
