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
import { useMock } from "@/components/MockProvider";
import type { Scenario } from "@/lib/types";
import { canRun } from "@/lib/permissions";
import { Button } from "@/components/ui/button";
export function AgentChat({ scenario }: { scenario: Scenario }) {
  const { state, role, dispatch } = useMock();
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
            <span className="badge gray">
              Deterministic demo · Not a live LLM
            </span>
          </div>
        )}
        {messages.map((run) => (
          <div className="chat-exchange" key={run.id}>
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
                {run.status === "waiting_approval" && (
                  <Link className="button" href="/approvals">
                    Review pending action →
                  </Link>
                )}
                <Link
                  className="text-link"
                  href={`/agents/opspilot/traces?trace=${run.traceId}`}
                >
                  Open R2M trace ↗
                </Link>
              </div>
            </div>
          </div>
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
                ? "Resolve the pending approval to continue…"
                : "Ask OpsPilot to inspect payments-api…"
            }
            disabled={!canRun(role) || pending || !released}
          />
          <Button
            variant="default"
            aria-label="Send demo message"
            disabled={!canRun(role) || pending || !released || !input.trim()}
            type="submit"
          >
            <ArrowUp size={18} />
          </Button>
        </form>
        <p>
          {!released
            ? "Build proposed: complete build evaluations, policy approval and release before sending a message."
            : !canRun(role)
              ? "Choose Atlas developer or release manager to run a scenario."
              : `Selected scenario controls the simulated outcome: ${scenario}. Your message is context only.`}
        </p>
      </div>
    </div>
  );
}
