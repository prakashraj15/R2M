"""R2M SDK public API. Agents import only from here."""
from .approvals import ActionGrant, arguments_hash, canonical_json
from .client import SDK_VERSION, ExecutionScope, R2MClient
from .context import current_execution, current_span_id, resume_action
from .policy import Policy, PolicyContext, PolicyResult, compute_artifact_hash, policy
from .redact import redact
from .types import (ApprovalRequired, AuthorizationResult, ConfigurationError, CostSource, Coverage, Decision,
                    EventKind, GrantInvalid, PolicyActivationError, PolicyDenied, R2MError, Risk, Severity,
                    SpanKind, Status, TransportError)

__version__ = SDK_VERSION
__all__ = [
    "ActionGrant", "ApprovalRequired", "AuthorizationResult", "ConfigurationError", "CostSource", "Coverage",
    "Decision", "EventKind", "ExecutionScope", "GrantInvalid", "Policy", "PolicyActivationError", "PolicyContext",
    "PolicyDenied", "PolicyResult", "R2MClient", "R2MError", "Risk", "SDK_VERSION", "Severity", "SpanKind",
    "Status", "TransportError", "arguments_hash", "canonical_json", "compute_artifact_hash", "current_execution",
    "current_span_id", "policy", "redact", "resume_action",
]
