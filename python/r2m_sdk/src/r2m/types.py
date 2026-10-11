"""Enums, event schema, decision types and exceptions shared across the SDK."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "1.0"


class Decision(str, enum.Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"

    @property
    def strictness(self) -> int:
        return {Decision.ALLOW: 0, Decision.REQUIRE_APPROVAL: 1, Decision.DENY: 2}[self]

    @staticmethod
    def strictest(*decisions: "Decision") -> "Decision":
        return max(decisions, key=lambda d: d.strictness)


class SpanKind(str, enum.Enum):
    ORCHESTRATION = "orchestration"
    MODEL = "model"
    TOOL = "tool"
    MEMORY = "memory"
    POLICY = "policy"
    INFRA = "infra"
    INTEGRATION = "integration"


class EventKind(str, enum.Enum):
    EXECUTION_STARTED = "execution.started"
    EXECUTION_ENDED = "execution.ended"
    SPAN = "span"
    STATE_TRANSITION = "state.transition"
    MODEL_CALL = "model.call"
    TOOL_CALL = "tool.call"
    POLICY_DECISION = "policy.decision"
    ACTION_RESULT = "action.result"
    USAGE = "usage"
    HEARTBEAT = "heartbeat"
    INSIGHT = "insight"
    ERROR = "error"


class Severity(str, enum.Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Status(str, enum.Enum):
    RUNNING = "running"
    OK = "ok"
    ERROR = "error"
    DENIED = "denied"
    PENDING_APPROVAL = "pending_approval"


class CostSource(str, enum.Enum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    ALLOCATED = "allocated"
    SIMULATED = "simulated"


class Risk(str, enum.Enum):
    LOW = "low"
    HIGH = "high"


class Coverage(str, enum.Enum):
    """How strongly R2M can vouch for a tool call. Observed != enforced."""

    OBSERVED = "observed"  # traced only; host could still call it uninstrumented
    ENFORCED = "enforced"  # passed policy gate + server grant before executing


@dataclass(frozen=True)
class AuthorizationResult:
    decision: Decision
    reason_codes: tuple[str, ...]
    decision_id: str | None
    action_id: str | None
    policy_revision_ids: tuple[str, ...] = ()
    grant: dict[str, Any] | None = None
    approval_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class R2MError(Exception):
    """Base class for SDK errors."""


class TransportError(R2MError):
    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class ConfigurationError(R2MError):
    pass


class PolicyDenied(R2MError):
    def __init__(self, tool: str, reason_codes: tuple[str, ...], *, action_id: str | None = None,
                 decision_id: str | None = None):
        super().__init__(f"{tool} denied: {', '.join(reason_codes) or 'no reason'}")
        self.tool = tool
        self.reason_codes = reason_codes
        self.action_id = action_id
        self.decision_id = decision_id


class ApprovalRequired(R2MError):
    def __init__(self, tool: str, reason_codes: tuple[str, ...], *, action_id: str | None,
                 approval_id: str | None, decision_id: str | None = None):
        super().__init__(f"{tool} requires approval: {', '.join(reason_codes)}")
        self.tool = tool
        self.reason_codes = reason_codes
        self.action_id = action_id
        self.approval_id = approval_id
        self.decision_id = decision_id


class PolicyActivationError(PolicyDenied):
    """A policy bound to a sensitive tool is not registered/verified; fail closed."""


class GrantInvalid(PolicyDenied):
    """The server grant does not bind exactly this action; fail closed."""
