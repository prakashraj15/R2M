"""Runtime action gate (docs/SDK_CONTRACT.md §3–4): ALLOW | DENY | REQUIRE_APPROVAL with HMAC-signed,
single-use, action-bound grants.

The SDK evaluates code-owned policies locally and reports per-policy results. The server never lets that
verdict *weaken* enforcement: it re-checks tenant scope, deployment state, active approved policy hashes,
that every policy governing the tool is cited, and exact-action approvals. Every check fails closed.
"""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from ..errors import ApiError, conflict, not_found
from .evidence_builder import audit, record_evidence
from .policy_registry import active_revisions
from .trace_ingest import ensure_execution, sanitize

GRANT_FIELDS = ("grant_id", "action_id", "decision_id", "customer_org_id", "deployment_id", "policy_revision_ids",
                "tool", "arguments_hash", "execution_id", "expires_at", "nonce")
STRICTNESS = {"ALLOW": 0, "REQUIRE_APPROVAL": 1, "DENY": 2}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sign_grant(grant: dict, key: str) -> str:
    """Byte-identical to r2m.approvals.sign_grant: HMAC-SHA256 over canonical JSON of GRANT_FIELDS."""
    payload = json.dumps({k: grant[k] for k in GRANT_FIELDS}, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, default=str).encode()
    return hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


async def authorize(conn, req, settings) -> dict:
    dep = await conn.fetchrow(
        """SELECT d.id, d.status, d.installation_id, i.customer_org_id, i.agent_id, i.environment
           FROM deployments d JOIN agent_installations i ON i.id = d.installation_id WHERE d.id=$1""", req.deployment_id)
    if (not dep or dep["installation_id"] != req.installation_id or dep["agent_id"] != req.agent_id
            or dep["customer_org_id"] != req.customer_org_id or dep["environment"] != req.environment):
        # Nothing can be persisted against an inconsistent scope.
        return _response("DENY", ["TENANT_SCOPE_INVALID"], None, None, [], None, None)

    async with conn.transaction():
        if not await ensure_execution(conn, req.execution_id, dep["id"], dep["customer_org_id"], req.trace_id,
                                      datetime.now(timezone.utc)):
            raise conflict("execution is bound to a different deployment or trace")
        if req.span_id:
            await conn.execute(
                """INSERT INTO spans(id, execution_id, kind, name, status, started_at)
                   VALUES ($1,$2,'unknown','(pending)','placeholder',now()) ON CONFLICT (id) DO NOTHING""",
                req.span_id, req.execution_id)

        action = None
        if req.action_id:
            action = await conn.fetchrow(
                "SELECT id, tool_key, arguments_hash, execution_id FROM tool_actions WHERE id=$1 FOR UPDATE", req.action_id)
            if (not action or action["tool_key"] != req.tool or action["arguments_hash"] != req.arguments_hash
                    or action["execution_id"] != req.execution_id):
                return _response("DENY", ["ACTION_BINDING_MISMATCH"], None, None, [], None, None)
        if not action:
            action = await conn.fetchrow(
                """INSERT INTO tool_actions(execution_id, span_id, tool_key, arguments_hash, arguments)
                   VALUES ($1,$2,$3,$4,$5) RETURNING id""",
                req.execution_id, req.span_id, req.tool, req.arguments_hash, sanitize(req.arguments or {}))

        decision, reasons, revisions, approval = await _evaluate(conn, req, dep, action["id"], settings)
        action_id = action["id"]

        await conn.execute(
            # Later decisions (e.g. a replayed resume) are recorded in policy_decisions but never rewrite an
            # action that already executed.
            """UPDATE tool_actions SET outcome=$2, authorized_at = CASE WHEN $3 THEN now() ELSE authorized_at END
               WHERE id=$1 AND executed_at IS NULL""", action_id,
            {"ALLOW": "authorized", "DENY": "denied", "REQUIRE_APPROVAL": "pending_approval"}[decision], decision == "ALLOW")
        decision_ids = []
        for rev in revisions or [None]:
            decision_ids.append(await conn.fetchval(
                """INSERT INTO policy_decisions(execution_id, action_id, revision_id, decision, reason_code, details)
                   VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
                req.execution_id, action_id, rev["id"] if rev else None, decision.lower(), ",".join(reasons)[:500],
                {"tool": req.tool, "risk": req.risk, "arguments_hash": req.arguments_hash,
                 "local_decision": req.local_decision, "local_results": [p.model_dump() for p in req.policies],
                 "approval_id": approval["id"] if approval else None,
                 "policy": {"key": rev["policy_key"], "version": rev["version"], "hash": rev["artifact_hash"]} if rev else None}))

        revision_ids = [r["id"] for r in revisions]
        grant = None
        if decision == "ALLOW":
            if approval:  # one grant per approval
                await conn.execute("UPDATE runtime_approvals SET status='consumed' WHERE id=$1", approval["id"])
            nonce = secrets.token_hex(32)
            expires = datetime.now(timezone.utc) + timedelta(seconds=settings.grant_ttl_seconds)
            grant_id = await conn.fetchval(
                """INSERT INTO action_grants(action_id, customer_org_id, deployment_id, execution_id, policy_revision_ids,
                   tool_key, arguments_hash, nonce_hash, expires_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id""",
                action_id, dep["customer_org_id"], dep["id"], req.execution_id, revision_ids, req.tool,
                req.arguments_hash, _sha256(nonce), expires)
            grant = {"grant_id": str(grant_id), "action_id": str(action_id), "decision_id": str(decision_ids[0]),
                     "customer_org_id": str(dep["customer_org_id"]), "deployment_id": str(dep["id"]),
                     "policy_revision_ids": [str(r) for r in revision_ids], "tool": req.tool,
                     "arguments_hash": req.arguments_hash, "execution_id": str(req.execution_id),
                     "expires_at": expires.isoformat(), "nonce": nonce}
            grant["signature"] = sign_grant(grant, settings.grant_signing_key)

        await record_evidence(conn, dep["installation_id"], "action_decision",
                              {"action_id": action_id, "decision": decision, "reason_codes": reasons, "tool": req.tool,
                               "arguments_hash": req.arguments_hash, "decision_ids": decision_ids,
                               "approval_id": approval["id"] if approval else None,
                               "grant_id": grant["grant_id"] if grant else None},
                              execution_id=req.execution_id, policy_revision_id=revision_ids[0] if revision_ids else None)
    return _response(decision, reasons, decision_ids[0], action_id, revision_ids,
                     approval["id"] if approval else None, approval["status"] if approval else None, grant)


def _response(decision, reasons, decision_id, action_id, revision_ids, approval_id, approval_status, grant=None) -> dict:
    return {"decision": decision, "reason_codes": reasons, "decision_id": decision_id, "action_id": action_id,
            "policy_revision_ids": revision_ids, "approval_id": approval_id, "approval_status": approval_status,
            "grant": grant}


async def _evaluate(conn, req, dep, action_id: UUID, settings):
    """Returns (decision, reason_codes, cited_revisions, approval_row|None). Order matters: fail closed first."""
    if dep["status"] != "deployed":
        return "DENY", ["DEPLOYMENT_NOT_ACTIVE"], [], None

    active = {r["policy_key"]: r for r in await active_revisions(conn, dep["installation_id"])}
    cited, unapproved = [], []
    for p in req.policies:
        rev = active.get(p.policy_id)
        if rev and rev["artifact_hash"] == p.artifact_hash and rev["version"] == p.version:
            cited.append(rev)
        else:
            unapproved.append(f"POLICY_NOT_APPROVED:{p.policy_id}")
    if unapproved:
        return "DENY", unapproved, cited, None
    # Every policy ever registered for this agent that governs this tool must be cited, so a build that
    # drops the decorator's policy binding cannot authorize the tool on its own.
    governing = await conn.fetch(
        "SELECT DISTINCT policy_key FROM policy_revisions WHERE agent_id=$1 AND definition_metadata->'tools' ? $2",
        dep["agent_id"], req.tool)
    missing = sorted({g["policy_key"] for g in governing} - {c["policy_key"] for c in cited})
    if missing:
        return "DENY", [f"GOVERNING_POLICY_NOT_CITED:{k}" for k in missing], cited, None

    # Strictest of the overall local verdict and each per-policy verdict; the server never relaxes it.
    local = max([req.local_decision, *(p.decision for p in req.policies)], key=STRICTNESS.get)
    local_codes = [p.reason_code for p in req.policies if p.decision == local and p.reason_code]
    if local == "DENY":
        return "DENY", local_codes or ["LOCAL_POLICY_DENY"], cited, None
    if local == "ALLOW":
        return "ALLOW", ["ALLOWED"], cited, None

    approval = await conn.fetchrow(
        "SELECT id, status, expires_at FROM runtime_approvals WHERE action_id=$1 ORDER BY requested_at DESC LIMIT 1 FOR UPDATE",
        action_id)
    if not approval:
        approval = await conn.fetchrow(
            """INSERT INTO runtime_approvals(action_id, status, expires_at)
               VALUES ($1,'pending', now() + make_interval(secs => $2)) RETURNING id, status, expires_at""",
            action_id, settings.runtime_approval_ttl_seconds)
    status = approval["status"]
    if status in ("pending", "approved") and approval["expires_at"] <= datetime.now(timezone.utc):
        await conn.execute("UPDATE runtime_approvals SET status='expired' WHERE id=$1", approval["id"])
        status = "expired"
    if status == "pending":
        return "REQUIRE_APPROVAL", local_codes or ["HUMAN_APPROVAL_REQUIRED"], cited, approval
    if status != "approved":
        return "DENY", [f"APPROVAL_{status.upper()}"], cited, {**dict(approval), "status": status}
    return "ALLOW", ["HUMAN_APPROVED"], cited, approval


async def record_result(conn, action_id: UUID, body) -> dict:
    async with conn.transaction():
        action = await conn.fetchrow(
            """SELECT a.id, a.authorized_at, a.executed_at, a.execution_id, d.installation_id FROM tool_actions a
               JOIN executions e ON e.id = a.execution_id JOIN deployments d ON d.id = e.deployment_id
               WHERE a.id=$1 FOR UPDATE OF a""", action_id)
        if not action:
            raise ApiError(404, "action_not_found", "unknown action")
        if action["authorized_at"] is None:
            raise ApiError(409, "not_authorized", "action was never authorized; result rejected")
        metadata = sanitize(body.result_metadata)
        if body.phase == "executed":
            if not body.grant_id or not body.nonce:
                raise ApiError(422, "validation_error", "executed phase requires grant_id and nonce")
            grant = await conn.fetchrow(
                "SELECT id, nonce_hash, expires_at, consumed_at FROM action_grants WHERE id=$1 AND action_id=$2 FOR UPDATE",
                body.grant_id, action_id)
            if not grant or not hmac.compare_digest(grant["nonce_hash"], _sha256(body.nonce)):
                raise ApiError(409, "grant_invalid", "grant does not belong to this action")
            if grant["consumed_at"] is not None:
                raise ApiError(409, "grant_already_consumed", "grant nonce already used")
            if grant["expires_at"] <= datetime.now(timezone.utc):
                raise ApiError(409, "grant_expired", "grant expired before the result was reported")
            await conn.execute("UPDATE action_grants SET consumed_at=now() WHERE id=$1", grant["id"])
            await conn.execute(
                """UPDATE tool_actions SET outcome=$2, executed_at=coalesce(executed_at, $3, now()),
                   result_metadata = result_metadata || $4 WHERE id=$1""",
                action_id, body.outcome, body.executed_at, {"error_class": body.error_class, "executed": metadata})
            await conn.execute("UPDATE runtime_approvals SET status='consumed' WHERE action_id=$1 AND status='approved'", action_id)
        else:
            if action["executed_at"] is None:
                raise ApiError(409, "not_executed", "cannot verify an action that was not executed")
            await conn.execute(
                """UPDATE tool_actions SET outcome=$2, verified_at = CASE WHEN $2 = 'verified' THEN coalesce($3, now()) END,
                   result_metadata = result_metadata || $4 WHERE id=$1""",
                action_id, body.outcome, body.verified_at, {"verification": metadata})
        await record_evidence(conn, action["installation_id"], f"action_{body.phase}",
                              {"action_id": action_id, "phase": body.phase, "outcome": body.outcome,
                               "grant_id": body.grant_id, "error_class": body.error_class, "result": metadata},
                              execution_id=action["execution_id"])
    return {"action_id": action_id, "recorded": True}


async def claim_grant(conn, execution_id: UUID, tool: str, customer_org_id: UUID):
    """Infrastructure-boundary check: atomically mark the oldest live grant for this execution+tool as applied.

    Independent of the SDK: a mutation that never went through /actions/authorize has no grant to claim.
    """
    return await conn.fetchrow(
        """UPDATE action_grants SET applied_at = now() WHERE id = (
             SELECT id FROM action_grants WHERE execution_id=$1 AND tool_key=$2 AND customer_org_id=$3
               AND applied_at IS NULL AND expires_at > now() ORDER BY issued_at LIMIT 1 FOR UPDATE SKIP LOCKED)
           RETURNING id, action_id, execution_id""", execution_id, tool, customer_org_id)


async def decide_runtime_approval(conn, actor, approval_id: UUID, decision: str, reason: str | None, request_id) -> dict:
    async with conn.transaction():
        row = await conn.fetchrow(
            """SELECT ra.id, ra.status, ra.expires_at, a.id AS action_id, a.tool_key, a.arguments_hash, a.arguments,
                      e.customer_org_id, e.id AS execution_id, d.installation_id
               FROM runtime_approvals ra JOIN tool_actions a ON a.id = ra.action_id
               JOIN executions e ON e.id = a.execution_id JOIN deployments d ON d.id = e.deployment_id
               WHERE ra.id=$1 FOR UPDATE OF ra""", approval_id)
        if not row:
            raise not_found("approval")
        actor.require("approval.decide", row["customer_org_id"])
        if decision == "revoke":
            raise conflict("runtime approvals are approved or rejected, not revoked")
        if row["status"] != "pending":
            raise conflict(f"approval is {row['status']}")
        if row["expires_at"] and row["expires_at"] <= datetime.now(timezone.utc):
            await conn.execute("UPDATE runtime_approvals SET status='expired' WHERE id=$1", approval_id)
            raise conflict("approval request expired")
        status = "approved" if decision == "approve" else "rejected"
        # Approved: the agent has a fresh, bounded window to resume exactly this action.
        await conn.execute(
            """UPDATE runtime_approvals SET status=$2, reviewer_id=$3, decided_at=now(),
               expires_at = now() + make_interval(secs => 600) WHERE id=$1""", approval_id, status, actor.user_id)
        body = {"approval_id": approval_id, "action_id": row["action_id"], "decision": status, "reason": reason,
                "tool": row["tool_key"], "arguments": row["arguments"], "arguments_hash": row["arguments_hash"],
                "decided_by": actor.email}
        await record_evidence(conn, row["installation_id"], f"runtime_approval_{status}", body, execution_id=row["execution_id"])
        await audit(conn, actor.user_id, row["customer_org_id"], f"runtime_approval.{decision}", "runtime_approval",
                    approval_id, request_id, body)
    return {"approval_id": approval_id, "status": status}
