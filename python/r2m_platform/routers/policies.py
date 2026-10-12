from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ..auth import Actor, SdkPrincipal, agent_installations
from ..dependencies import actor, db, sdk
from ..errors import not_found
from ..schemas import PolicyRegistration, PolicySubmitIn
from ..services import policy_registry

router = APIRouter(tags=["policies"])


@router.get("/agents/{agent_id}/policies")
async def policies(agent_id: UUID, installation_id: UUID | None = None, a: Actor = Depends(actor), conn=Depends(db)):
    ids = [i["id"] for i in await agent_installations(conn, a, agent_id, installation_id)]
    revisions = await conn.fetch(
        """SELECT r.id, r.policy_key, r.version, r.description, r.artifact_hash, r.enforcement_point,
                  r.definition_metadata, r.created_at, u.email AS owner_email
           FROM policy_revisions r LEFT JOIN users u ON u.id = r.owner_user_id
           WHERE r.agent_id=$1 ORDER BY r.policy_key, r.created_at DESC""", agent_id)
    subs = await conn.fetch(
        """SELECT s.id, s.revision_id, s.installation_id, s.status, s.requested_at, s.resolved_at, su.email AS submitted_by,
                  (SELECT json_agg(json_build_object('decision', d.decision, 'reason', d.reason, 'by', du.email, 'at', d.created_at)
                           ORDER BY d.created_at)
                   FROM approval_decisions d JOIN users du ON du.id = d.decided_by WHERE d.submission_id = s.id) AS history,
                  EXISTS(SELECT 1 FROM policy_activations pa WHERE pa.submission_id = s.id AND pa.active) AS active
           FROM policy_submissions s JOIN users su ON su.id = s.submitted_by
           WHERE s.installation_id = ANY($1::uuid[]) ORDER BY s.requested_at DESC""", ids)
    decisions = await conn.fetch(
        """SELECT pd.revision_id, pd.decision, count(*) AS n FROM policy_decisions pd
           JOIN executions e ON e.id = pd.execution_id JOIN deployments d ON d.id = e.deployment_id
           WHERE d.installation_id = ANY($1::uuid[]) GROUP BY 1, 2""", ids)
    out = []
    for r in revisions:
        out.append({**dict(r),
                    "submissions": [dict(s) for s in subs if s["revision_id"] == r["id"]],
                    "operational_decisions": {d["decision"]: d["n"] for d in decisions if d["revision_id"] == r["id"]},
                    "coverage_caveat": "Enforced only on SDK-guarded tool paths; uninstrumented calls are not covered."})
    return {"policies": out}


@router.post("/agents/{agent_id}/policies/register")
async def register(agent_id: UUID, body: PolicyRegistration, p: SdkPrincipal = Depends(sdk), conn=Depends(db)):
    if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM agents WHERE id=$1 AND vendor_org_id=$2)", agent_id, p.vendor_org_id):
        raise not_found("agent")
    if body.installation_id and not await conn.fetchval(
            """SELECT EXISTS(SELECT 1 FROM agent_installations WHERE id=$1 AND agent_id=$2 AND customer_org_id=$3)""",
            body.installation_id, agent_id, p.customer_org_id):
        raise not_found("installation")
    build_id = None
    if body.deployment_id:  # RLS + explicit checks: the deployment must be this agent's, at this customer
        build_id = await conn.fetchval(
            """SELECT d.build_id FROM deployments d JOIN agent_installations i ON i.id = d.installation_id
               WHERE d.id=$1 AND i.agent_id=$2 AND i.customer_org_id=$3""",
            body.deployment_id, agent_id, p.customer_org_id)
        if not build_id:
            raise not_found("deployment")
    return {"policies": await policy_registry.register(conn, agent_id, body.policies, body.installation_id, build_id)}


@router.post("/agents/{agent_id}/policies/{revision_id}/submit", status_code=201)
async def submit(agent_id: UUID, revision_id: UUID, body: PolicySubmitIn, request: Request,
                 a: Actor = Depends(actor), conn=Depends(db)):
    inst = (await agent_installations(conn, a, agent_id, body.installation_id))[0]
    return await policy_registry.submit(conn, a, revision_id, inst, body.note, request.state.request_id)
