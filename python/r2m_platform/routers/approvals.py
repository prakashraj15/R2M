from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ..auth import Actor, scoped_installations
from ..dependencies import actor, db
from ..errors import not_found
from ..schemas import DecisionIn
from ..services import authorization, policy_registry

router = APIRouter(tags=["approvals"])


@router.get("/approvals")
async def approvals(status: str | None = None, a: Actor = Depends(actor), conn=Depends(db)):
    ids = [i["id"] for i in await scoped_installations(conn, a)]
    policy = await conn.fetch(
        """SELECT 'policy' AS kind, s.id, s.status, s.requested_at, s.installation_id, i.customer_org_id, s.submitted_by,
                  su.email AS submitted_by_email, r.policy_key, r.version, r.artifact_hash, r.description,
                  r.definition_metadata->'tools' AS tools, ag.name AS agent_name, ag.id AS agent_id
           FROM policy_submissions s JOIN policy_revisions r ON r.id = s.revision_id JOIN users su ON su.id = s.submitted_by
           JOIN agent_installations i ON i.id = s.installation_id JOIN agents ag ON ag.id = i.agent_id
           WHERE s.installation_id = ANY($1::uuid[]) AND ($2::text IS NULL OR s.status = $2)
           ORDER BY s.requested_at DESC LIMIT 200""", ids, status)
    runtime = await conn.fetch(
        """SELECT 'runtime_action' AS kind, ra.id, ra.status, ra.requested_at, ra.expires_at, d.installation_id,
                  e.customer_org_id, a.tool_key, a.arguments, a.arguments_hash, e.trace_id, e.id AS execution_id,
                  ag.name AS agent_name, ag.id AS agent_id,
                  (SELECT reason_code FROM policy_decisions pd WHERE pd.action_id = a.id LIMIT 1) AS reason_code
           FROM runtime_approvals ra JOIN tool_actions a ON a.id = ra.action_id JOIN executions e ON e.id = a.execution_id
           JOIN deployments d ON d.id = e.deployment_id JOIN agent_installations i ON i.id = d.installation_id
           JOIN agents ag ON ag.id = i.agent_id
           WHERE d.installation_id = ANY($1::uuid[]) AND ($2::text IS NULL OR ra.status = $2)
           ORDER BY ra.requested_at DESC LIMIT 200""", ids, status)
    items = [{**dict(r), "can_decide": r["status"] == "pending" and a.can("approval.decide", r["customer_org_id"])
              and r.get("submitted_by") != a.user_id} for r in [*policy, *runtime]]
    return {"approvals": sorted(items, key=lambda x: x["requested_at"], reverse=True)}


@router.post("/approvals/{approval_id}/decision")
async def decide(approval_id: UUID, body: DecisionIn, request: Request, a: Actor = Depends(actor), conn=Depends(db)):
    ids = [i["id"] for i in await scoped_installations(conn, a)]
    if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM policy_submissions WHERE id=$1 AND installation_id = ANY($2::uuid[]))",
                           approval_id, ids):
        return await policy_registry.decide_submission(conn, a, approval_id, body.decision, body.reason, request.state.request_id)
    if await conn.fetchval(
            """SELECT EXISTS(SELECT 1 FROM runtime_approvals ra JOIN tool_actions t ON t.id = ra.action_id
               JOIN executions e ON e.id = t.execution_id JOIN deployments d ON d.id = e.deployment_id
               WHERE ra.id=$1 AND d.installation_id = ANY($2::uuid[]))""", approval_id, ids):
        return await authorization.decide_runtime_approval(conn, a, approval_id, body.decision, body.reason, request.state.request_id)
    raise not_found("approval")
