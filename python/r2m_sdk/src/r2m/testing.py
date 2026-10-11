"""In-memory fake of the R2M platform API for SDK/agent tests and offline evals.

Implements the SDK-facing endpoints from docs/SDK_CONTRACT.md over ``httpx.MockTransport``,
including the backend's stricter rules (§7 of the contract): proposed builds, governing-policy
citation, one grant per approval, rejected tampered policies and execution-required events.
It is a test double, not the platform: the real logic lives in ``r2m_platform``.
"""
from __future__ import annotations

import json
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .approvals import sign_grant

_NS = uuid.UUID("6f1c2a3e-0000-4000-8000-000000000002")
_STRICT = {"ALLOW": 0, "REQUIRE_APPROVAL": 1, "DENY": 2}


def _id(*parts: str) -> str:
    return str(uuid.uuid5(_NS, "/".join(parts)))


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class FakeAction:
    action_id: str
    tool: str
    arguments_hash: str
    execution_id: str
    approval_status: str | None = None  # pending | approved | rejected | consumed | expired
    approval_id: str | None = None
    approval_expires_at: datetime | None = None
    executed: bool = False
    results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FakeGrant:
    grant_id: str
    action_id: str
    execution_id: str
    tool: str
    expires_at: datetime
    applied: bool = False


class FakePlatform:
    def __init__(self, *, grant_key: str = "test-token", grant_ttl_s: int = 60, auto_deploy: bool = True,
                 approval_ttl_s: int = 600) -> None:
        self.grant_key = grant_key
        self.grant_ttl_s = grant_ttl_s
        self.approval_ttl_s = approval_ttl_s
        self.auto_deploy = auto_deploy  # False: new builds are 'proposed' like the real backend
        self.events: dict[str, dict[str, Any]] = {}
        self.rejected_events: list[dict[str, Any]] = []
        self.ingest_calls = 0
        self.deployments: dict[str, str] = {}  # deployment_id -> status
        self.registered_policies: dict[str, dict[str, Any]] = {}  # policy_id -> latest accepted manifest
        self.policy_versions: dict[tuple[str, str], str] = {}  # (id, version) -> artifact_hash
        self.approved_hashes: set[str] = set()  # activated (customer-approved) artifact hashes
        self.actions: dict[str, FakeAction] = {}
        self.grants: list[FakeGrant] = []
        self.decisions: list[dict[str, Any]] = []
        self.incidents: list[dict[str, Any]] = []
        self.consumed_nonces: set[str] = set()
        self.down = False
        self.fail_ingest_times = 0
        self.auto_approve_policies = True
        self.tamper_grant: dict[str, Any] | None = None  # overrides applied after signing (tests)

    # ---- test controls -------------------------------------------------
    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def deploy(self, deployment_id: str) -> None:
        self.deployments[deployment_id] = "deployed"

    def approve_action(self, action_id: str) -> None:
        a = self.actions[action_id]
        a.approval_status = "approved"
        a.approval_expires_at = _now() + timedelta(seconds=self.approval_ttl_s)

    def approve_pending(self) -> list[str]:
        ids = [a.action_id for a in self.actions.values() if a.approval_status == "pending"]
        for i in ids:
            self.approve_action(i)
        return ids

    def reject_action(self, action_id: str) -> None:
        self.actions[action_id].approval_status = "rejected"

    def revoke_policy(self, artifact_hash: str) -> None:
        self.approved_hashes.discard(artifact_hash)

    def claim_grant(self, execution_id: str, tool: str) -> FakeGrant | None:
        """Infrastructure-boundary check mirroring r2m_platform.services.authorization.claim_grant."""
        for g in self.grants:
            if g.execution_id == execution_id and g.tool == tool and not g.applied and g.expires_at > _now():
                g.applied = True
                return g
        return None

    def events_of(self, kind: str) -> list[dict[str, Any]]:
        return sorted((e for e in self.events.values() if e["kind"] == kind), key=lambda e: e["occurred_at"])

    # ---- routing -------------------------------------------------------
    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("platform down", request=request)
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        routes = [
            (r"^/api/v1/agents$", self._register_agent),
            (r"^/api/v1/agents/([^/]+)/policies/register$", self._register_policies),
            (r"^/api/v1/actions/authorize$", self._authorize),
            (r"^/api/v1/actions/([^/]+)/result$", self._result),
            (r"^/api/v1/ingest/events$", self._ingest),
        ]
        for pattern, handler in routes:
            m = re.match(pattern, path)
            if m and request.method == "POST":
                status, payload = handler(body, *m.groups())
                return httpx.Response(status, json=payload)
        return httpx.Response(404, json={"code": "not_found", "message": path, "request_id": None})

    def _register_agent(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        agent_id = _id("agent", body["vendor_org_id"], body["slug"])
        inst = _id("installation", agent_id, body["customer_org_id"], body["environment"])
        dep = _id("deployment", inst, body["build"]["artifact_digest"])
        if dep not in self.deployments:
            self.deployments[dep] = "deployed" if self.auto_deploy else "proposed"
        self.agent = body
        return 200, {"agent_id": agent_id, "installation_id": inst, "deployment_id": dep,
                     "deployment_status": self.deployments[dep]}

    def _register_policies(self, body: dict[str, Any], agent_id: str) -> tuple[int, dict[str, Any]]:
        out = []
        for m in body["policies"]:
            known = self.policy_versions.get((m["id"], m["version"]))
            if known is not None and known != m["artifact_hash"]:
                self.incidents.append({"category": f"policy_hash_mismatch:{m['id']}", "severity": "high"})
                out.append({"policy_id": m["id"], "version": m["version"], "artifact_hash": m["artifact_hash"],
                            "revision_id": None, "hash_matches": False, "status": "rejected"})
                continue
            self.policy_versions[(m["id"], m["version"])] = m["artifact_hash"]
            self.registered_policies[m["id"]] = m
            if self.auto_approve_policies:
                self.approved_hashes.add(m["artifact_hash"])
            out.append({
                "policy_id": m["id"], "version": m["version"], "artifact_hash": m["artifact_hash"],
                "revision_id": _id("revision", agent_id, m["id"], m["version"], m["artifact_hash"]),
                "hash_matches": True,
                "status": "active" if m["artifact_hash"] in self.approved_hashes else "registered",
            })
        return 200, {"policies": out}

    def _authorize(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        revision_ids = [_id("revision", body["agent_id"], p["policy_id"], p["version"], p["artifact_hash"])
                        for p in body["policies"]]
        if body.get("action_id"):
            action = self.actions.get(body["action_id"])
            if (action is None or action.tool != body["tool"] or action.arguments_hash != body["arguments_hash"]
                    or action.execution_id != body["execution_id"]):
                return self._decide(body, "DENY", ["ACTION_BINDING_MISMATCH"], None, [])
        else:
            action = FakeAction(str(uuid.uuid4()), body["tool"], body["arguments_hash"], body["execution_id"])
            self.actions[action.action_id] = action

        if self.deployments.get(body["deployment_id"]) != "deployed":
            return self._decide(body, "DENY", ["DEPLOYMENT_NOT_ACTIVE"], action, [])
        unapproved = [p["policy_id"] for p in body["policies"] if p["artifact_hash"] not in self.approved_hashes]
        if unapproved:
            return self._decide(body, "DENY", [f"POLICY_NOT_APPROVED:{p}" for p in unapproved], action, revision_ids)
        governing = {pid for pid, m in self.registered_policies.items() if body["tool"] in m["tools"]}
        missing = sorted(governing - {p["policy_id"] for p in body["policies"]})
        if missing:
            return self._decide(body, "DENY", [f"GOVERNING_POLICY_NOT_CITED:{k}" for k in missing], action,
                                revision_ids)

        local = max([body["local_decision"], *(p["decision"] for p in body["policies"])], key=_STRICT.get)
        codes = [p["reason_code"] for p in body["policies"] if p["decision"] == local and p["reason_code"]]
        if local == "DENY":
            return self._decide(body, "DENY", codes or ["LOCAL_POLICY_DENY"], action, revision_ids)
        if local == "ALLOW":
            return self._decide(body, "ALLOW", ["ALLOWED"], action, revision_ids)

        if action.approval_status is None:
            action.approval_status = "pending"
            action.approval_id = str(uuid.uuid4())
            action.approval_expires_at = _now() + timedelta(seconds=self.approval_ttl_s)
        if action.approval_status in ("pending", "approved") and action.approval_expires_at <= _now():
            action.approval_status = "expired"
        if action.approval_status == "pending":
            return self._decide(body, "REQUIRE_APPROVAL", codes or ["HUMAN_APPROVAL_REQUIRED"], action, revision_ids)
        if action.approval_status != "approved":
            return self._decide(body, "DENY", [f"APPROVAL_{action.approval_status.upper()}"], action, revision_ids)
        return self._decide(body, "ALLOW", ["HUMAN_APPROVED"], action, revision_ids, approval_status="approved")

    def _decide(self, body: dict[str, Any], decision: str, reasons: list[str], action: FakeAction | None,
                revision_ids: list[str], approval_status: str | None = None) -> tuple[int, dict[str, Any]]:
        decision_id = str(uuid.uuid4())
        resp: dict[str, Any] = {
            "decision": decision, "reason_codes": reasons, "decision_id": decision_id,
            "action_id": action.action_id if action else None, "policy_revision_ids": revision_ids,
            "approval_id": action.approval_id if action else None,
            "approval_status": approval_status or (action.approval_status if action else None),
            "grant": None,
        }
        if decision == "ALLOW" and action is not None:
            if approval_status == "approved":
                action.approval_status = "consumed"  # one grant per approval
            expires = _now() + timedelta(seconds=self.grant_ttl_s)
            grant = {
                "grant_id": str(uuid.uuid4()), "action_id": action.action_id, "decision_id": decision_id,
                "customer_org_id": body["customer_org_id"], "deployment_id": body["deployment_id"],
                "policy_revision_ids": revision_ids, "tool": body["tool"], "arguments_hash": body["arguments_hash"],
                "execution_id": body["execution_id"], "expires_at": expires.isoformat(),
                "nonce": secrets.token_hex(16),
            }
            grant["signature"] = sign_grant(grant, self.grant_key)
            if self.tamper_grant:
                grant.update(self.tamper_grant)
            resp["grant"] = grant
            self.grants.append(FakeGrant(grant["grant_id"], action.action_id, body["execution_id"], body["tool"],
                                         expires))
        self.decisions.append({"request": body, "response": resp})
        return 200, resp

    def _result(self, body: dict[str, Any], action_id: str) -> tuple[int, dict[str, Any]]:
        action = self.actions.get(action_id)
        if action is None:
            return 404, {"code": "action_not_found", "message": "unknown action", "request_id": None}
        if body.get("phase", "executed") == "executed":
            if body.get("nonce") in self.consumed_nonces:
                return 409, {"code": "grant_already_consumed", "message": "nonce reused", "request_id": None}
            self.consumed_nonces.add(body["nonce"])
            action.executed = True
        elif not action.executed:
            return 409, {"code": "not_executed", "message": "cannot verify", "request_id": None}
        action.results.append(body)
        return 200, {"action_id": action_id, "recorded": True}

    def _ingest(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self.ingest_calls += 1
        if self.fail_ingest_times > 0:
            self.fail_ingest_times -= 1
            return 503, {"code": "unavailable", "message": "try again", "request_id": None}
        accepted = duplicates = 0
        rejected = []
        for e in body["events"]:
            if e.get("execution_id") is None and e["kind"] != "heartbeat":
                rejected.append({"event_id": e["event_id"], "code": "execution_required"})
                self.rejected_events.append(e)
            elif e["event_id"] in self.events:
                duplicates += 1
            else:
                self.events[e["event_id"]] = {**e, "received_at": _now().isoformat()}
                accepted += 1
        return 200, {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}
