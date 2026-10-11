"use client";
import Link from "next/link";
import type { Span } from "@/lib/types";
import { Panel, Badge } from "@/components/ui/shared";
export function EventDetail({ span }: { span: Span }) {
  return (
    <Panel
      title="Event detail"
      subtitle={span.id}
      action={<Badge tone="gray">Sanitized</Badge>}
    >
      <div className="panel-body">
        <h3>{span.name}</h3>
        <p className="body-copy">{span.summary}</p>
        <pre>
          {JSON.stringify(
            {
              kind: span.kind,
              status: span.status,
              policy: span.policy || null,
              capture: "metadata_only",
              source: "simulated",
            },
            null,
            2,
          )}
        </pre>
        {span.policy && (
          <Link className="text-link" href="/agents/opspilot/policies">
            Inspect {span.policy} →
          </Link>
        )}
        <p className="helper">
          No private reasoning, raw prompts, or proprietary source is captured.
        </p>
      </div>
    </Panel>
  );
}
