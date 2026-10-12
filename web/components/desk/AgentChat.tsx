"use client";
import { useState } from "react";
import Link from "next/link";
import {
  Bot,
  ArrowUp,
  User,
  CheckCircle2,
  Clock3,
  CircleX,
} from "lucide-react";
import { useR2M } from "@/components/R2MProvider";
import type { Scenario } from "@/lib/types";
import { canRun } from "@/lib/permissions";
import { Button } from "@/components/ui/button";
import { cp } from "@/lib/live-adapter";
import { motion } from "@/components/ui/motion";
export function AgentChat({ scenario }: { scenario: Scenario }) {
  const { state, role, dispatch, base } = useR2M();
  const { identity } = state;
  const [input, setInput] = useState("");
  const messages = state.runs.filter((run) => run.prompt).toReversed();
  const pending = state.runs.some((run) => run.status === "waiting_approval");
  // R2M, not the browser, enforces release: an unreleased build may chat and observe, but every change is denied.
  const build = state.builds[0];
  const released = build?.deploymentStatus === "deployed";
  function send() {
    if (
      input.trim() &&
      dispatch({ type: "run", scenario, prompt: input.trim() })
    )
      setInput("");
  }
  return (
    <div className="chat">
      <div className="chat-history">
        {!messages.length && (
          <div className="chat-welcome">
            <div className="agent-avatar large">
              <Bot size={30} />
            </div>
            <h2>Meet {identity.agent}.</h2>
            <p>
              Observe the service. Understand the issue.
              <br />
              Act only within an approved boundary.
            </p>
            <span className="badge green">Live agent · governed by R2M</span>
          </div>
        )}
        {messages.map((run) => (
          <motion.div
            className="chat-exchange"
            key={`${run.id}-${run.decision ?? ""}`}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="chat-message user">
              <User size={16} />
              <p>{run.prompt}</p>
            </div>
            <div className="chat-message">
              <Bot size={18} />
              <div>
                <strong>
                  {identity.agent} <small>{run.id}</small>
                </strong>
                <p>{run.recommendation}</p>
                <div className="chat-timeline">
                  {run.spans
                    .filter((span) => span.status !== "not_reached")
                    .map((span) => (
                      <div key={span.id} data-status={span.status}>
                        {span.status === "passed" ? (
                          <CheckCircle2 size={13} />
                        ) : span.status === "waiting" ? (
                          <Clock3 size={13} />
                        ) : (
                          <CircleX size={13} />
                        )}
                        {span.name}
                        <small>{span.status}</small>
                      </div>
                    ))}
                </div>
                {run.decision && (
                  <p>
                    <strong>R2M decision:</strong> {run.decision} {(run.reasons || []).join(", ")}
                  </p>
                )}
                {run.status === "waiting_approval" && (
                  <a className="button" href={cp("/approvals")}>
                    Review pending action →
                  </a>
                )}
                {run.traceId && (
                  <a className="text-link" href={cp(`${base}/traces?trace=${run.traceId}`)}>
                    Open R2M trace ↗
                  </a>
                )}
              </div>
            </div>
          </motion.div>
        ))}
      </div>
      <div className="chat-input">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            send();
          }}
        >
          <input
            aria-label={`Message ${identity.agent}`}
            value={input}
            maxLength={2000}
            onChange={(event) => setInput(event.target.value)}
            placeholder={
              pending
                ? "After approving in R2M, say “approved, continue”…"
                : `Ask ${identity.agent} to inspect ${identity.service}…`
            }
            disabled={!canRun(role)}
          />
          <Button
            variant="default"
            aria-label="Send message"
            disabled={!canRun(role) || !input.trim()}
            type="submit"
          >
            <ArrowUp size={18} />
          </Button>
        </form>
        <p>
          {!canRun(role)
            ? `Your role can watch ${identity.agent} but not instruct it; approvals happen in the R2M control plane.`
            : build && !released
              ? `Build ${build.version} is ${build.deploymentStatus} in R2M: ${identity.agent} can observe, but every change is denied until a release manager deploys it.`
              : `Live agent · build ${build?.version ?? "…"} · scenario: ${scenario}. Replies can take up to 40 s.`}
        </p>
      </div>
    </div>
  );
}
