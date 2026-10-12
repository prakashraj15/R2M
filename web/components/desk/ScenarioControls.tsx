"use client";
import type { Scenario } from "@/lib/types";
import { useR2M } from "@/components/R2MProvider";
import { Button } from "@/components/ui/button";
import { canRun } from "@/lib/permissions";
export function ScenarioControls({
  scenario,
  onChange,
}: {
  scenario: Scenario;
  onChange: (scenario: Scenario) => void;
}) {
  const { reset, role, state } = useR2M();
  const pending = state.runs.some((r) => r.status === "waiting_approval");
  return (
    <div className="scenario-controls">
      <div className="field-label">SCENARIO</div>
      {(
        [
          [
            "healthy",
            "Healthy observation",
            "Inspect health; no action needed.",
          ],
          ["degraded", "Degraded service", "Diagnose with a safe fallback."],
          [
            "rollback",
            "Approval-required rollback",
            "Pause before changing the service.",
          ],
        ] as const
      ).map(([id, title, description]) => (
        <button
          disabled={pending}
          key={id}
          className={`scenario-card ${scenario === id ? "selected" : ""}`}
          onClick={() => onChange(id)}
        >
          <span className="radio-dot" />
          <div>
            <strong>{title}</strong>
            <small>{description}</small>
          </div>
        </button>
      ))}
      <p className="helper">
        Faulty-build testing is available in Build evaluations, not the runtime
        controls.
      </p>
      <Button variant="ghost" disabled={!canRun(role)} onClick={() => reset()}>
        Reset service to baseline
      </Button>
    </div>
  );
}
