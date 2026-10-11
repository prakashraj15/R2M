"use client";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Check, ChevronDown, RotateCcw } from "lucide-react";
import { useMock } from "@/components/MockProvider";

export function DemoGuide() {
  const { state, reset } = useMock();
  const [open, setOpen] = useState(false);
  const policy = state.approvals.some(
    (a) =>
      a.kind === "policy" &&
      a.policy === "DEPLOY-001" &&
      a.status === "approved",
  );
  const deployed = state.builds.some(
    (b) => b.id === "build-safe" && b.deployed,
  );
  const action = state.approvals.find((a) => a.kind === "action");
  const run = state.runs.find((r) => r.id === action?.executionId);
  const steps = [
    {
      title: "Approve the policy",
      detail:
        "Meridian Financial · Security reviewer. Review DEPLOY-001 and enter a decision reason.",
      href: "/approvals",
      done: policy,
    },
    {
      title: "Release the safe build",
      detail:
        "Atlas Applied AI · Release manager. Review build checks, evaluate release eligibility, then simulate deployment of safe-1.0.",
      href: "/agents/opspilot/evaluations",
      done: deployed,
    },
    {
      title: "Request a rollback",
      detail:
        "Atlas Applied AI · Developer or release manager. Select the rollback scenario and send a message.",
      href: "/demo/agent",
      done: !!action,
    },
    {
      title: "Review the exact action",
      detail:
        "Meridian Financial · Security reviewer. Open Operational actions and approve or reject the specific rollback.",
      href: "/approvals",
      done: !!action && action.status !== "pending",
    },
  ];
  const next = steps.find((s) => !s.done);
  return (
    <section className="demo-guide" aria-label="Demo walkthrough">
      <button
        className="guide-toggle"
        aria-expanded={open}
        aria-controls="demo-guide-content"
        onClick={() => setOpen(!open)}
      >
        <span className="guide-pill">DEMO GUIDE</span>
        <span>
          {next
            ? `Next: ${next.title}`
            : "Decision recorded · Explore the evidence"}
        </span>
        <small>{steps.filter((s) => s.done).length} / 4</small>
        <ChevronDown size={16} />
      </button>
      {open && (
        <div id="demo-guide-content" className="guide-content">
          <ol className="guide-steps">
            {steps.map((step, i) => (
              <li key={step.title}>
                <span
                  className={
                    step.done ? "guide-number complete" : "guide-number"
                  }
                >
                  {step.done ? (
                    <Check size={14} aria-label="Completed" />
                  ) : (
                    i + 1
                  )}
                </span>
                <div>
                  <Link href={step.href}>
                    {step.title} <ArrowRight size={12} />
                  </Link>
                  <p>{step.detail}</p>
                </div>
              </li>
            ))}
          </ol>
          <div className="guide-footer">
            <span>
              Local simulation · Use the organization and role selectors to
              change perspective.
            </span>
            {run && (
              <Link
                className="text-link"
                href={`/agents/opspilot/traces?trace=${run.traceId}`}
              >
                Inspect this execution →
              </Link>
            )}
            <button className="button" onClick={reset}>
              <RotateCcw size={13} /> Reset demo data
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
