"use client";
export function DemoGuide() {
  return (
    <details className="demo-guide">
      <summary className="guide-toggle">
        <span className="guide-pill">LIVE DEMO GUIDE</span>Message → policy →
        approval → verified effect
      </summary>
      <div className="guide-content">
        <ol className="live-guide">
          <li>
            <strong>Talk to OpsPilot.</strong> Meridian Operations can ask about
            payments-api. A proposed build cannot act; if the server returns “No
            deployed build”, complete release first.
          </li>
          <li>
            <strong>Release safe-1.0.</strong> CI publishes evaluations. Atlas
            Developer submits the three policies; Meridian Security approves;
            Atlas Release evaluates and deploys. faulty-1.0 stays blocked.
          </li>
          <li>
            <strong>Degraded + Keewano.</strong> Reset degraded, then ask
            “payments-api is throwing errors, fix it”. Inspect the returned
            history and proposal.
          </li>
          <li>
            <strong>Approve the exact action.</strong> Meridian Security reviews
            the actual tool and arguments in Approvals.
          </li>
          <li>
            <strong>Continue.</strong> Return to chat, refresh approval state
            and send Continue. Confirm the returned decision, verification and
            service state.
          </li>
          <li>
            <strong>Fault injection.</strong> Atlas Developer resets faulty and
            asks “Run the faulty build rollback”. Inspect the returned refusal
            and Security incident. Customers get normal governed tools.
          </li>
        </ol>
      </div>
    </details>
  );
}
