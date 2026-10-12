"use client";
import Link from "next/link";
import { Bot, ArrowUpRight } from "lucide-react";
import { useR2M } from "@/components/R2MProvider";
import { releaseChecks } from "@/lib/release";
import { Badge } from "@/components/ui/shared";
import { money } from "@/lib/format";
export function AgentCard() {
  const { state, base } = useR2M();
  const { identity } = state;
  const deployed = state.builds.find((b) => b.deployed);
  const eligible = state.builds.some((b) => Object.values(releaseChecks(state, b.id)).every(Boolean));
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
              <Link className="agent-identity" href={base}>
                <div className="agent-avatar">
                  <Bot size={22} />
                </div>
                <div>
                  <strong>{identity.agent}</strong>
                  <small>{identity.vendor}</small>
                </div>
              </Link>
            </td>
            <td>
              {identity.customer}<small>{identity.environment} · {deployed?.version ?? "no deployed build"}</small>
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
              <small>Model cost · recent runs</small>
            </td>
            <td>
              <Link
                aria-label={`Open ${identity.agent}`}
                className="icon-link"
                href={base}
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
