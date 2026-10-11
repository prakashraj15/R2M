"use client";
import { useState, useEffect } from "react";
import Link from "next/link";
import { useLive, errorText } from "@/components/live/LiveProvider";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
import { request, api } from "@/lib/api";
import {
  scenarioTitles,
  metric,
  modeLabel,
  insightLabel,
  type Integration,
  type LiveScenario,
} from "@/lib/live-types";
export default function Page() {
  const live = useLive();
  const [input, setInput] = useState("");
  const [integration, setIntegration] = useState<Integration | null>(null);
  const [toggleBusy, setToggleBusy] = useState(false);
  const [toggleError, setToggleError] = useState("");
  useEffect(() => {
    setIntegration(null);
    if (live.session)
      request<Integration>("/integrations/keewano")
        .then(setIntegration)
        .catch((e) => setToggleError(errorText(e)));
  }, [live.session]);
  const latest = live.turns.at(-1)?.response;
  const service = live.state?.services[0];
  const canChat = live.can("demo.use");
  const disabled = live.busy || live.loading || !live.state || !canChat;
  const approval =
    live.state?.approvals.find((a) => a.id === latest?.approval_id) ||
    live.state?.approvals.find((a) => a.status === "approved");
  const insight = latest?.insight;
  const base = live.state ? `/agents/${live.state.agent_id}` : "";
  const query = live.state
    ? `installation_id=${encodeURIComponent(live.state.installation_id)}`
    : "";
  async function send(text: string) {
    if (await live.send(text)) setInput("");
  }
  async function toggle(enabled: boolean) {
    if (!live.state) return;
    setToggleBusy(true);
    setToggleError("");
    try {
      await api.configureIntegration(live.state.customer_org_id, enabled);
      setIntegration(await request<Integration>("/integrations/keewano"));
    } catch (e) {
      setToggleError(errorText(e));
    } finally {
      setToggleBusy(false);
    }
  }
  const config = integration?.organizations.find(
    (o) => o.organization_id === live.state?.customer_org_id,
  );
  return (
    <>
      <PageHeader
        eyebrow="OpsPilot / Connected agent"
        title="Operations desk"
        description="Your message drives the agent. Every action remains subject to R2M controls."
        actions={
          <Badge tone="gray">
            {latest ? modeLabel(latest) : "Waiting for agent response"}
          </Badge>
        }
      />
      {latest?.build?.deployment_status === "proposed" && (
        <div className="soft-note">
          Build {latest.build.version} not released yet. Actions require
          release.
        </div>
      )}
      <div className="demo-grid">
        <aside className="panel">
          <div className="service-state">
            <h3>{service?.service_key || "Service state"}</h3>
            <Badge
              tone={
                !service?.health_status || service.health_status === "unknown"
                  ? "gray"
                  : undefined
              }
            >
              {service?.health_status || "Unknown"}
            </Badge>
            <div className="detail-grid">
              {[
                ["Deployment", service?.deployment_version || "Unknown"],
                ["Replicas", metric(service?.replicas)],
                ["Error rate", metric(service?.error_rate_pct, "%")],
                ["P95 latency", metric(service?.p95_latency_ms, " ms")],
                ["CPU", metric(service?.cpu_pct, "%")],
                ["Memory", metric(service?.memory_pct, "%")],
              ].map(([k, v]) => (
                <div className="kv" key={k}>
                  <span>{k}</span>
                  <strong>{v}</strong>
                </div>
              ))}
            </div>
            <p className="helper">
              {live.state?.notice || "No service telemetry loaded."}
            </p>
          </div>
          <div className="scenario-controls">
            <div className="field-label">RESET STARTING WORLD</div>
            {(
              live.state?.scenarios ||
              (["healthy", "degraded", "approval", "faulty"] as LiveScenario[])
            ).map((s) => (
              <button
                key={s}
                className={`button ${live.scenario === s ? "button-primary" : ""}`}
                disabled={disabled}
                onClick={() => live.reset(s)}
              >
                {scenarioTitles[s] || s}
              </button>
            ))}
            <p className="helper">
              Reset expires pending approvals. Faulty is a vendor-only test
              path; customers see normal governed behaviour.
            </p>
          </div>
        </aside>
        <Panel title="Conversation" className="chat-panel">
          <div className="chat">
            <div className="chat-history" aria-live="polite">
              {!live.turns.length && (
                <div className="chat-welcome">
                  <h2>What should OpsPilot investigate?</h2>
                  <p>
                    Ask about health, investigate errors, or request an action.
                  </p>
                </div>
              )}
              {live.turns.map((turn, i) => (
                <div className="chat-exchange" key={i}>
                  <div className="chat-message user">
                    <p>{turn.prompt}</p>
                  </div>
                  <div className="chat-message">
                    <div>
                      <strong>OpsPilot</strong>{" "}
                      <Badge tone="gray">{modeLabel(turn.response)}</Badge>
                      <p className="plain-reply">{turn.response.reply}</p>
                      {turn.response.decision && (
                        <Badge
                          tone={
                            ["DENY", "FAILED"].includes(turn.response.decision)
                              ? "red"
                              : turn.response.decision === "REQUIRE_APPROVAL"
                                ? "amber"
                                : "green"
                          }
                        >
                          {turn.response.decision}
                        </Badge>
                      )}
                      <p className="helper">
                        Cost provenance: {turn.response.cost_label || "Unknown"}
                      </p>
                      {turn.response.reasons?.map((r) => (
                        <code className="reason-code" key={r}>
                          {r}
                        </code>
                      ))}
                      <ol className="live-timeline">
                        {turn.response.steps?.map((s, n) => (
                          <li key={`${s}-${n}`}>{s.replaceAll("_", " ")}</li>
                        ))}
                      </ol>
                      {turn.response.trace_id && (
                        <Link
                          className="text-link"
                          href={`${base}/traces?trace=${encodeURIComponent(turn.response.trace_id)}&${query}`}
                        >
                          Open R2M trace →
                        </Link>
                      )}
                      {turn.response.service_after && (
                        <p>
                          Returned deployment:{" "}
                          {turn.response.service_after.deployment_version} ·
                          Verified:{" "}
                          {String(turn.response.verified ?? "Unknown")}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
              {live.busy && (
                <p role="status" className="soft-note">
                  OpsPilot is working… Model and tool calls can take several
                  seconds.
                </p>
              )}
            </div>
            <div className="chat-input">
              <div className="button-row">
                {latest?.suggestions?.map((s) => (
                  <button
                    className="button"
                    key={s}
                    disabled={disabled}
                    onClick={() => setInput(s)}
                  >
                    {s}
                  </button>
                ))}
                {approval?.status === "approved" && (
                  <button
                    className="button button-primary"
                    disabled={disabled}
                    onClick={() => send("continue")}
                  >
                    Continue
                  </button>
                )}
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!disabled && input.trim()) void send(input);
                }}
              >
                <input
                  aria-label="Message OpsPilot"
                  placeholder="How is payments-api doing?"
                  maxLength={2000}
                  disabled={disabled}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                />
                <button
                  className="button button-primary"
                  type="submit"
                  disabled={disabled || !input.trim()}
                >
                  Send
                </button>
              </form>
              <p>
                Scenario sets the starting world. Your message determines what
                the agent proposes.
              </p>
            </div>
          </div>
        </Panel>
        <div className="demo-right">
          <Panel title="Action & authorization">
            <div className="panel-body">
              {latest?.proposal ? (
                <>
                  <Badge tone="gray">
                    {latest.proposal.source === "keewano"
                      ? "Keewano-informed"
                      : latest.proposal.source}
                  </Badge>
                  <h3>{latest.proposal.tool}</h3>
                  <pre>
                    {JSON.stringify(latest.proposal.arguments, null, 2)}
                  </pre>
                  <p className="body-copy">{latest.proposal.rationale}</p>
                  {latest.decision === "REQUIRE_APPROVAL" && (
                    <p>
                      Awaiting Meridian security approval. Approval alone does
                      not execute the action.
                    </p>
                  )}
                  {latest.approval_id && (
                    <Link
                      className="button"
                      href={`/approvals?approval=${encodeURIComponent(latest.approval_id)}`}
                    >
                      Review in R2M →
                    </Link>
                  )}
                  <p>
                    Approval status: {approval?.status || "Refresh to check"}
                  </p>
                </>
              ) : (
                <p>No action proposed this turn.</p>
              )}
              {live.state?.recent_actions
                .filter((a) => !a.authorized)
                .map((a, i) => (
                  <div className="live-error" key={i}>
                    Refused bypass: {a.kind} · {a.created_at}
                  </div>
                ))}
            </div>
          </Panel>
          <Panel title="Historical intelligence">
            <div className="panel-body">
              <p>{insightLabel(insight)}</p>
              {insight?.status === "ok" &&
                insight.supported &&
                insight.candidates?.map((c) => (
                  <div key={c.remediation} className="history-candidate">
                    <span>
                      {c.remediation} · {c.successes}/{c.samples}
                    </span>
                    <progress
                      max={Math.max(1, c.samples)}
                      value={c.successes}
                    />
                  </div>
                ))}
              <p className="helper">
                Untrusted advisory data. History never authorizes an action.
              </p>
              {integration && (
                <p className="helper">
                  Platform:{" "}
                  {integration.platform_enabled ? "enabled" : "disabled"} ·
                  Adapter:{" "}
                  {integration.adapter_installed ? "installed" : "unavailable"}
                </p>
              )}
              {live.state &&
                live.can(
                  "integration.configure",
                  live.state.customer_org_id,
                ) && (
                  <button
                    className="button"
                    disabled={toggleBusy || live.busy}
                    onClick={() => toggle(!config?.enabled)}
                  >
                    {config?.enabled ? "Disable" : "Enable"} Keewano
                  </button>
                )}
              {toggleError && <p role="alert">{toggleError}</p>}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
