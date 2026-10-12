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
  const { state, role, dispatch } = useR2M();
  const [input, setInput] = useState("");
  const messages = state.runs.filter((run) => run.prompt).toReversed();
  const pending = state.runs.some((run) => run.status === "waiting_approval");
  const released = state.builds.some((build) => build.deployed);
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
            <h2>Meet OpsPilot.</h2>
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
                  OpsPilot <small>{run.id}</small>
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
                  <a className="text-link" href={cp(`/agents/opspilot/traces?trace=${run.traceId}`)}>
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
            aria-label="Message OpsPilot"
            value={input}
            maxLength={2000}
            onChange={(event) => setInput(event.target.value)}
            placeholder={
              pending
                ? "After approving in R2M, say “approved, continue”…"
                : "Ask OpsPilot to inspect payments-api…"
            }
            disabled={!canRun(role) || !released}
          />
          <Button
            variant="default"
            aria-label="Send message"
            disabled={!canRun(role) || !released || !input.trim()}
            type="submit"
          >
            <ArrowUp size={18} />
          </Button>
        </form>
        <p>
          {!released
            ? "Build proposed: complete build evaluations, policy approval and release before sending a message."
            : !canRun(role)
              ? "Security reviewers approve in R2M; switch to Operations or Atlas developer to chat."
              : `Live agent · scenario: ${scenario}. Replies can take up to 40 s.`}
        </p>
      </div>
    </div>
  );
}
