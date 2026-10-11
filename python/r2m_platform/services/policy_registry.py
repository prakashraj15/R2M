"""Code-owned policy revisions: hash registration, submission, approval and activation state."""
from uuid import UUID

from ..errors import ApiError, conflict, forbidden
from .evidence_builder import audit, record_evidence
from .incident_detector import open_incident

REVISION_COLUMNS = "r.id, r.agent_id, r.policy_key, r.version, r.description, r.artifact_hash, r.enforcement_point, r.definition_metadata, r.owner_user_id, r.created_at"


async def register(conn, agent_id: UUID, policies, installation_id: UUID | None) -> list[dict]:
    """Idempotent per (key, version, hash). Same version with a different hash is tampering: not stored,
    reported with hash_matches=false (the SDK then fails closed) and raised as an incident."""
    out = []
    async with conn.transaction():
        for p in policies:
            existing = await conn.fetchrow(
                "SELECT id, artifact_hash FROM policy_revisions WHERE agent_id=$1 AND policy_key=$2 AND version=$3 ORDER BY created_at LIMIT 1",
                agent_id, p.id, p.version)
            if existing and existing["artifact_hash"] != p.artifact_hash:
                if installation_id:
                    await open_incident(conn, installation_id, f"policy_hash_mismatch:{p.id}", "high",
                                        f"{p.id}@{p.version} registered with code that differs from the stored revision")
                out.append({"policy_id": p.id, "version": p.version, "artifact_hash": p.artifact_hash,
                            "revision_id": None, "hash_matches": False, "status": "rejected"})
                continue
            metadata = {"tools": p.tools, "scope": p.scope, "owner": p.owner, "source_file": p.source_file}
            rev_id = existing["id"] if existing else await conn.fetchval(
                """INSERT INTO policy_revisions(agent_id, policy_key, version, description, artifact_hash, enforcement_point, definition_metadata)
                   VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
                agent_id, p.id, p.version, p.description, p.artifact_hash, p.enforcement_point, metadata)
            status = "registered"
            if installation_id:
                status = await conn.fetchval(
                    """SELECT CASE WHEN EXISTS(SELECT 1 FROM policy_activations WHERE installation_id=$1 AND revision_id=$2 AND active)
                                   THEN 'active' ELSE coalesce((SELECT status FROM policy_submissions
                                   WHERE installation_id=$1 AND revision_id=$2), 'registered') END""",
                    installation_id, rev_id)
                status = {"approved": "registered", "rejected": "registered", "withdrawn": "registered"}.get(status, status)
            out.append({"policy_id": p.id, "version": p.version, "artifact_hash": p.artifact_hash,
                        "revision_id": rev_id, "hash_matches": True, "status": status})
    return out


async def active_revisions(conn, installation_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        f"""SELECT {REVISION_COLUMNS} FROM policy_activations a JOIN policy_revisions r ON r.id = a.revision_id
            WHERE a.installation_id=$1 AND a.active AND (a.expires_at IS NULL OR a.expires_at > now())""",
        installation_id)
    return [dict(r) for r in rows]


async def submit(conn, actor, revision_id: UUID, installation: dict, note: str | None, request_id: str | None) -> dict:
    actor.require("policy.submit", installation["vendor_org_id"])
    rev = await conn.fetchrow(f"SELECT {REVISION_COLUMNS} FROM policy_revisions r WHERE r.id=$1 AND r.agent_id=$2",
                              revision_id, installation["agent_id"])
    if not rev:
        raise ApiError(404, "not_found", "policy revision not found")
    async with conn.transaction():
        existing = await conn.fetchrow(
            "SELECT id, status FROM policy_submissions WHERE revision_id=$1 AND installation_id=$2 FOR UPDATE",
            revision_id, installation["id"])
        if existing and existing["status"] in ("pending", "approved"):
            raise conflict(f"revision already {existing['status']} for this installation")
        if existing:
            sub_id = existing["id"]
            await conn.execute(
                """UPDATE policy_submissions SET status='pending', submitted_by=$2, requested_at=now(), resolved_at=NULL
                   WHERE id=$1""", sub_id, actor.user_id)
        else:
            sub_id = await conn.fetchval(
                "INSERT INTO policy_submissions(revision_id, installation_id, submitted_by) VALUES ($1,$2,$3) RETURNING id",
                revision_id, installation["id"], actor.user_id)
        if rev["owner_user_id"] is None:
            await conn.execute("UPDATE policy_revisions SET owner_user_id=$2 WHERE id=$1", revision_id, actor.user_id)
        latest_evals = await conn.fetch(
            """SELECT b.version, s.suite_key, er.status FROM evaluation_runs er JOIN builds b ON b.id = er.build_id
               JOIN evaluation_suites s ON s.id = er.suite_id WHERE b.agent_id=$1 ORDER BY er.started_at DESC LIMIT 10""",
            installation["agent_id"])
        body = {"submission_id": sub_id, "policy_key": rev["policy_key"], "version": rev["version"],
                "artifact_hash": rev["artifact_hash"], "affected_tools": rev["definition_metadata"].get("tools", []),
                "recent_evaluations": [dict(e) for e in latest_evals], "note": note, "submitted_by": actor.email}
        await record_evidence(conn, installation["id"], "policy_submitted", body, policy_revision_id=revision_id)
        await audit(conn, actor.user_id, installation["vendor_org_id"], "policy.submit", "policy_submission", sub_id, request_id, body)
    return {"submission_id": sub_id, "status": "pending"}


async def decide_submission(conn, actor, submission_id: UUID, decision: str, reason: str | None, request_id: str | None) -> dict:
    async with conn.transaction():
        sub = await conn.fetchrow(
            """SELECT s.*, i.customer_org_id, r.policy_key, r.agent_id, r.artifact_hash, r.version
               FROM policy_submissions s JOIN agent_installations i ON i.id = s.installation_id
               JOIN policy_revisions r ON r.id = s.revision_id WHERE s.id=$1 FOR UPDATE OF s""", submission_id)
        actor.require("approval.decide", sub["customer_org_id"])
        if sub["submitted_by"] == actor.user_id:
            raise forbidden("the submitter cannot decide their own policy submission")
        allowed = {"approve": "pending", "reject": "pending", "revoke": "approved"}[decision]
        if sub["status"] != allowed:
            raise conflict(f"cannot {decision} a submission in status {sub['status']}")
        await conn.execute(
            "INSERT INTO approval_decisions(submission_id, decided_by, decision, reason) VALUES ($1,$2,$3,$4)",
            submission_id, actor.user_id, decision, reason)
        new_status = {"approve": "approved", "reject": "rejected", "revoke": "revoked"}[decision]
        await conn.execute("UPDATE policy_submissions SET status=$2, resolved_at=now() WHERE id=$1", submission_id, new_status)
        if decision in ("approve", "revoke"):
            # Approval supersedes every other active revision of the same policy key; revoke deactivates this one.
            await conn.execute(
                """UPDATE policy_activations SET active=false, revoked_at=now()
                   WHERE installation_id=$1 AND active AND revision_id IN
                   (SELECT id FROM policy_revisions WHERE agent_id=$2 AND policy_key=$3)""",
                sub["installation_id"], sub["agent_id"], sub["policy_key"])
        if decision == "approve":
            await conn.execute(
                """INSERT INTO policy_activations(submission_id, revision_id, installation_id, artifact_hash)
                   VALUES ($1,$2,$3,$4)""", submission_id, sub["revision_id"], sub["installation_id"], sub["artifact_hash"])
        body = {"submission_id": submission_id, "decision": decision, "reason": reason, "decided_by": actor.email,
                "policy_key": sub["policy_key"], "version": sub["version"], "artifact_hash": sub["artifact_hash"]}
        await record_evidence(conn, sub["installation_id"], f"policy_{new_status}", body, policy_revision_id=sub["revision_id"])
        await audit(conn, actor.user_id, sub["customer_org_id"], f"policy.{decision}", "policy_submission", submission_id, request_id, body)
    return {"submission_id": submission_id, "status": new_status}
