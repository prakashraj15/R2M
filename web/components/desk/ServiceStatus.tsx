"use client";
import { useR2M } from "@/components/R2MProvider";
import { Badge } from "@/components/ui/shared";
import { Server } from "lucide-react";
export function ServiceStatus() {
  const { state } = useR2M();
  const s = state.service;
  return (
    <div className="service-state">
      <div className="service-icon">
        <Server size={23} />
      </div>
      <h3>payments-api</h3>
      <p>Meridian Financial · production</p>
      <Badge>{s.health}</Badge>
      <div className="service-metrics">
        <div>
          <strong>{s.version}</strong>
          <small>Deployment</small>
        </div>
        <div>
          <strong>{s.replicas}</strong>
          <small>Replicas</small>
        </div>
        <div>
          <strong>{s.errorRate}%</strong>
          <small>Error rate</small>
        </div>
        <div>
          <strong>{s.latency} ms</strong>
          <small>P95 latency</small>
        </div>
      </div>
      <div className="utilization">
        <span>
          CPU <strong>{s.cpu}%</strong>
        </span>
        <div>
          <i style={{ width: `${s.cpu}%` }} />
        </div>
        <span>
          Memory <strong>{s.memory}%</strong>
        </span>
        <div>
          <i style={{ width: `${s.memory}%` }} />
        </div>
      </div>
    </div>
  );
}
