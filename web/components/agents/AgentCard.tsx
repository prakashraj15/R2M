"use client";
import Link from "next/link";
import { Bot, ArrowUpRight } from "lucide-react";
import { useMock } from "@/components/MockProvider";
import { releaseChecks } from "@/lib/mock-engine";
import { Badge } from "@/components/ui/shared";
import { money } from "@/lib/format";
export function AgentCard() {
  const { state } = useMock();
  const eligible = Object.values(releaseChecks(state, "build-safe")).every(
    Boolean,
  );
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>AGENT / VENDOR</th>
            <th>DEPLOYMENT</th>
            <th>HEALTH</th>
            <th>RELEASE GATE</th>
            <th>MODEL COST</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <Link className="agent-identity" href="/agents/opspilot">
                <div className="agent-avatar">
                  <Bot size={22} />
                </div>
                <div>
                  <strong>OpsPilot</strong>
                  <small>Atlas Applied AI · Operations assistant</small>
                </div>
              </Link>
            </td>
            <td>
              Meridian Financial<small>Production simulation · safe-1.0</small>
            </td>
            <td>
              <Badge>{state.service.health}</Badge>
            </td>
            <td>
              <Badge>
                {state.builds.some((b) => b.deployed)
                  ? "Deployed"
                  : eligible
                    ? "Eligible"
                    : "Proposed"}
              </Badge>
            </td>
            <td>
              {money(state.runs.reduce((n, r) => n + r.cost, 0))}
              <small>Simulated model cost</small>
            </td>
            <td>
              <Link
                aria-label="Open OpsPilot"
                className="icon-link"
                href="/agents/opspilot"
              >
                <ArrowUpRight size={18} />
              </Link>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
