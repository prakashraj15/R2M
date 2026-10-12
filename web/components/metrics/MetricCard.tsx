"use client";
import { ArrowUpRight } from "lucide-react";
import { motion, rise } from "@/components/ui/motion";
export function MetricCard({
  label,
  value,
  detail,
  accent = false,
}: {
  label: string;
  value: string | number;
  detail: string;
  accent?: boolean;
}) {
  return (
    <motion.div
      className={`metric-card ${accent ? "accent" : ""}`}
      variants={rise}
      initial="hidden"
      animate="show"
      whileHover={{ y: -2 }}
    >
      <div>
        {label}
        <ArrowUpRight size={13} />
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </motion.div>
  );
}
