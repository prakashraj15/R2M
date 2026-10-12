"use client";
import { useState } from "react";
import Link from "next/link";
import { Check, LockKeyhole, X } from "lucide-react";
import { useR2M } from "@/components/R2MProvider";
import { releaseChecks } from "@/lib/release";
import { canEvaluate, canDeploy } from "@/lib/permissions";
import { PageHeader, Panel, Badge } from "@/components/ui/shared";
import { Button } from "@/components/ui/button";
export default function Page() {
  const { state, role, dispatch } = useR2M();
  const [id, setId] = useState("");
  const build = state.builds.find((b) => b.id === id) ?? state.builds[0];
  if (!build) return <p className="soft-note">No builds yet. Builds appear when OpsPilot registers and CI uploads evaluations.</p>;
  const checks = releaseChecks(state, build.id);
  const eligible = Object.values(checks).every(Boolean);
  return (
    <>
      <PageHeader
        eyebrow="OpsPilot / Pre-deployment assurance"
        title="Build evaluations"
        description="Test the artifact before release. Runtime policy decisions live in traces."
        actions={<Badge tone="gray">Build / CI only</Badge>}
      />
      <Panel
        title="Build registry"
        subtitle="Uploaded by CI (scripts/run_evals.py)"
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>BUILD</th>
                <th>ARTIFACT DIGEST</th>
                <th>MANDATORY CHECKS</th>
                <th>RELEASE</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {state.builds.map((b) => (
                <tr key={b.id} className={id === b.id ? "row-selected" : ""}>
                  <td>
                    <button className="table-link" onClick={() => setId(b.id)}>
                      {b.version}
                    </button>
                    <small>Oct 11 · policy-regression-v1</small>
                  </td>
                  <td>
                    <code>{b.digest}</code>
                  </td>
                  <td>
                    {b.cases.filter((c) => c.passed).length} / {b.cases.length}{" "}
                    passed
                  </td>
                  <td>
                    <Badge>
                      {b.deployed
                        ? "Deployed"
                        : Object.values(releaseChecks(state, b.id)).every(
                              Boolean,
                            )
                          ? "Eligible"
                          : "Blocked"}
                    </Badge>
                  </td>
                  <td>
                    <button className="text-link" onClick={() => setId(b.id)}>
                      Inspect →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="two-column section-gap">
        <Panel
          title={`${build.version} · policy-regression-v1`}
          subtitle="Expected versus actual for this build"
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>MANDATORY CASE</th>
                  <th>EXPECTED / ACTUAL</th>
                  <th>RESULT</th>
                </tr>
              </thead>
              <tbody>
                {build.cases.map((c) => (
                  <tr key={c.id}>
                    <td>
                      {c.name}
                      <small>{c.policy}</small>
                    </td>
                    <td>
                      {c.expected}
                      <small>{c.actual}</small>
                    </td>
                    <td>
                      <Badge>{c.passed ? "Passed" : "Failed"}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="panel-body">
            <Button
              onClick={() => dispatch({ type: "evaluate", id })}
              disabled={!canEvaluate(role)}
            >
              Refresh CI results
            </Button>
            {!canEvaluate(role) && (
              <p className="helper">
                Sign in as a release manager to evaluate or deploy
                builds.
              </p>
            )}
          </div>
        </Panel>
        <Panel
          title="Deployment eligibility"
          action={<LockKeyhole size={16} />}
        >
          <div className="panel-body">
            <div className="gate-list">
              {Object.entries(checks).map(([key, passed]) => (
                <div key={key}>
                  {passed ? <Check size={16} /> : <X size={16} />}
                  <span>
                    {
                      {
                        evaluations: "Mandatory evaluations pass",
                        policies: "Required policy revisions approved",
                        artifact: "Artifact digest matches the evaluated build",
                        scope: "Customer scope matches",
                      }[key]
                    }
                  </span>
                </div>
              ))}
            </div>
            <Badge>
              {build.deployed
                ? "Deployed"
                : eligible
                  ? "Eligible"
                  : "Release blocked"}
            </Badge>
            <p className="body-copy">
              Passing tests alone does not authorize release. The artifact and
              customer policy approvals must match.
            </p>
            <Button
              disabled={!canDeploy(role) || build.deployed}
              onClick={() => dispatch({ type: "evaluateRelease", id })}
            >
              Evaluate release eligibility
            </Button>
            <Button
              variant="default"
              disabled={
                !canDeploy(role) ||
                !eligible ||
                !build.releaseEvaluated ||
                build.deployed
              }
              onClick={() => dispatch({ type: "deploy", id })}
            >
              {build.deployed ? "Deployed" : "Deploy to production"}
            </Button>
            <div className="section-gap">
              <Link className="text-link" href="/approvals">
                Review required policies →
              </Link>
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}
