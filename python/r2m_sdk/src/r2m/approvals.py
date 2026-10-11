"""Exact-action approval binding: canonical argument hashing and grant verification.

A grant from ``POST /actions/authorize`` authorises exactly one execution of one tool
with one argument set. It is HMAC-SHA256 signed by the platform over the canonical
JSON of every field except ``signature`` (see docs/SDK_CONTRACT.md). The SDK verifies
signature, binding, expiry and nonce reuse before running the tool.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .types import GrantInvalid

GRANT_FIELDS = (
    "grant_id", "action_id", "decision_id", "customer_org_id", "deployment_id", "policy_revision_ids",
    "tool", "arguments_hash", "execution_id", "expires_at", "nonce",
)


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def arguments_hash(arguments: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(arguments)).hexdigest()


def sign_grant(body: dict[str, Any], key: str) -> str:
    payload = {k: body[k] for k in GRANT_FIELDS}
    return hmac.new(key.encode(), canonical_json(payload), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ActionGrant:
    grant_id: str
    action_id: str
    decision_id: str
    customer_org_id: str
    deployment_id: str
    policy_revision_ids: list[str]
    tool: str
    arguments_hash: str
    execution_id: str
    expires_at: str
    nonce: str
    signature: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionGrant":
        missing = [k for k in (*GRANT_FIELDS, "signature") if k not in data]
        if missing:
            raise GrantInvalid("grant", ("GRANT_MALFORMED",), action_id=data.get("action_id"))
        return cls(**{k: data[k] for k in (*GRANT_FIELDS, "signature")})

    def body(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in GRANT_FIELDS}


class GrantVerifier:
    """Verifies grants and remembers consumed nonces for this process."""

    def __init__(self, key: str) -> None:
        self._key = key
        self._used: set[str] = set()
        self._lock = threading.Lock()

    def verify(self, grant: ActionGrant, *, tool: str, args_hash: str, execution_id: str,
               customer_org_id: str, deployment_id: str, action_id: str | None,
               now: datetime | None = None) -> None:
        def fail(code: str) -> None:
            raise GrantInvalid(tool, (code,), action_id=grant.action_id, decision_id=grant.decision_id)

        expected = sign_grant(grant.body(), self._key)
        if not hmac.compare_digest(expected, grant.signature):
            fail("GRANT_BAD_SIGNATURE")
        if grant.tool != tool:
            fail("GRANT_TOOL_MISMATCH")
        if grant.arguments_hash != args_hash:
            fail("GRANT_ARGUMENTS_MISMATCH")
        if grant.execution_id != execution_id:
            fail("GRANT_EXECUTION_MISMATCH")
        if grant.customer_org_id != customer_org_id:
            fail("GRANT_ORG_MISMATCH")
        if grant.deployment_id != deployment_id:
            fail("GRANT_DEPLOYMENT_MISMATCH")
        if action_id is not None and grant.action_id != action_id:
            fail("GRANT_ACTION_MISMATCH")
        now = now or datetime.now(timezone.utc)
        try:
            expires = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
        except ValueError:
            fail("GRANT_MALFORMED")
        if expires.tzinfo is None or now >= expires:
            fail("GRANT_EXPIRED")
        with self._lock:
            if grant.nonce in self._used:
                fail("GRANT_NONCE_REUSED")
            self._used.add(grant.nonce)
