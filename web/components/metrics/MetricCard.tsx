import { ArrowUpRight } from "lucide-react";
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
    <div className={`metric-card ${accent ? "accent" : ""}`}>
      <div>
        {label}
        <ArrowUpRight size={13} />
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}
