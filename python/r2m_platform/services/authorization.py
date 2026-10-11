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

import asyncpg

from ..errors import ApiError, conflict, not_found
from .evidence_builder import audit, record_evidence
from .trace_ingest import sanitize

GRANT_FIELDS = ("grant_id", "action_id", "decision_id", "customer_org_id", "deployment_id", "policy_revision_ids",
                "tool", "arguments_hash", "execution_id", "expires_at", "nonce")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sign_grant(grant: dict, key: str) -> str:
    """Byte-identical to r2m.approvals.sign_grant: HMAC-SHA256 over canonical JSON of GRANT_FIELDS."""
    payload = json.dumps({k: grant[k] for k in GRANT_FIELDS}, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, default=str).encode()
    return hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


async def authorize(conn, req, settings, principal) -> dict:
    """One database round trip for the decision (db function r2m_authorize, migration 0005), then grant signing
    and evidence here. Evidence is written right after the decision commits; the decision, action and policy
    decision rows are the authoritative record."""
    nonce = secrets.token_hex(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.grant_ttl_seconds)
    payload = {**req.model_dump(mode="json"), "arguments": sanitize(req.arguments or {})}
    try:
        out = await conn.fetchval("SELECT r2m_authorize($1, $2, $3, $4, $5)", principal.customer_org_id, payload,
                                  _sha256(nonce), expires, settings.runtime_approval_ttl_seconds)
    except asyncpg.PostgresError as exc:
        if exc.sqlstate == "R2M20":
            raise conflict("execution is bound to a different deployment or trace")
        raise
    if "action_id" not in out:  # tenant scope / action binding: nothing to bind a grant or evidence to
        return _response(out["decision"], out["reason_codes"], None, None, [], None, None)

    decision, reasons, decision_ids = out["decision"], out["reason_codes"], out["decision_ids"]
    revision_ids = out["policy_revision_ids"]
    grant = None
    if decision == "ALLOW":
        grant = {"grant_id": out["grant_id"], "action_id": out["action_id"], "decision_id": decision_ids[0],
                 "customer_org_id": out["customer_org_id"], "deployment_id": out["deployment_id"],
                 "policy_revision_ids": revision_ids, "tool": req.tool, "arguments_hash": req.arguments_hash,
                 "execution_id": str(req.execution_id), "expires_at": expires.isoformat(), "nonce": nonce}
        # Unless a shared key is configured, sign with the caller's own token: exactly what the SDK
        # verifies with by default (GrantVerifier(grant_key or token)).
        grant["signature"] = sign_grant(grant, settings.grant_signing_key or principal.token)
    await record_evidence(conn, UUID(out["installation_id"]), "action_decision",
                          {"action_id": out["action_id"], "decision": decision.lower(), "reason_codes": reasons,
                           "tool": req.tool, "arguments_hash": req.arguments_hash, "decision_ids": decision_ids,
                           "approval_id": out["approval_id"], "grant_id": out["grant_id"]},
                          execution_id=req.execution_id, policy_revision_id=UUID(revision_ids[0]) if revision_ids else None)
    return _response(decision, reasons, decision_ids[0], out["action_id"], revision_ids, out["approval_id"],
                     out["approval_status"], grant)


def _response(decision, reasons, decision_id, action_id, revision_ids, approval_id, approval_status, grant=None) -> dict:
    return {"decision": decision, "reason_codes": reasons, "decision_id": decision_id, "action_id": action_id,
            "policy_revision_ids": revision_ids, "approval_id": approval_id, "approval_status": approval_status,
            "grant": grant}


async def record_result(conn, action_id: UUID, body, principal) -> dict:
    async with conn.transaction():
        action = await conn.fetchrow(
            """SELECT a.id, a.authorized_at, a.executed_at, a.execution_id, d.installation_id FROM tool_actions a
               JOIN executions e ON e.id = a.execution_id JOIN deployments d ON d.id = e.deployment_id
               WHERE a.id=$1 AND e.customer_org_id=$2 FOR UPDATE OF a""", action_id, principal.customer_org_id)
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
