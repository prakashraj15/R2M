"use client";
import type { Execution } from "@/lib/types";
import { Badge } from "@/components/ui/shared";
import { duration } from "@/lib/format";
export function TraceWaterfall({
  run,
  selected,
  onSelect,
}: {
  run: Execution;
  selected: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="waterfall">
      {run.spans.map((s) => (
        <button
          key={s.id}
          className={`waterfall-row ${s.id === selected ? "selected" : ""}`}
          onClick={() => onSelect(s.id)}
        >
          <div>
            <strong>{s.name}</strong>
            <small>{s.kind}</small>
          </div>
          <div className="waterfall-track">
            <span
              style={{
                marginLeft: `${(s.start / 950) * 70}%`,
                width: `${Math.max(2, (s.duration / 950) * 70)}%`,
              }}
              className={s.status}
            />
          </div>
          <span className="waterfall-duration">
            {s.status === "not_reached" ? "—" : duration(s.duration)}
          </span>
          <Badge
            tone={
              s.status === "passed"
                ? "green"
                : s.status === "not_reached"
                  ? "gray"
                  : "amber"
            }
          >
            {s.status.replaceAll("_", " ")}
          </Badge>
        </button>
      ))}
    </div>
  );
}
