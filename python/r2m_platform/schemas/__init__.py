"""Pydantic request contracts. Responses are plain JSON dicts documented in docs/API_CONTRACT.md."""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Str200 = Field(min_length=1, max_length=200)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DemoSessionIn(Strict):
    email: str = Field(min_length=3, max_length=200)


class Lenient(BaseModel):
    """SDK payloads: tolerate fields added by newer SDK versions instead of rejecting whole batches."""
    model_config = ConfigDict(extra="ignore")


Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")


# ---- SDK agent registration (docs/SDK_CONTRACT.md §1) ----------------------
class SdkBuild(Lenient):
    version: str = Field(min_length=1, max_length=50)
    source_digest: str = Digest
    artifact_digest: str = Digest


class SdkComponent(Lenient):
    component_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")
    kind: Literal["orchestrator", "model", "tool", "memory", "storage", "compute", "gateway"]
    label: str = Str200
    metadata: dict[str, Any] = Field(default_factory=dict)


class SdkEdge(Lenient):
    source: str = Field(max_length=100)
    target: str = Field(max_length=100)
    edge_kind: str = Field(default="calls", max_length=40)


class SdkTopology(Lenient):
    components: list[SdkComponent] = Field(default_factory=list, max_length=200)
    edges: list[SdkEdge] = Field(default_factory=list, max_length=500)


class SdkAgentIn(Lenient):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Str200
    description: str | None = Field(default=None, max_length=2000)
    sdk_version: str | None = Field(default=None, max_length=50)
    vendor_org_id: UUID
    customer_org_id: UUID
    environment: Literal["development", "staging", "production", "demo"]
    build: SdkBuild
    topology: SdkTopology = Field(default_factory=SdkTopology)


# ---- SDK ingestion (§5) ---------------------------------------------------
EventKind = Literal["execution.started", "execution.ended", "span", "state.transition", "model.call", "tool.call",
                    "policy.decision", "action.result", "usage", "heartbeat", "insight", "error"]


class IngestEvent(Lenient):
    event_id: UUID
    schema_version: str = Field(default="1.0", max_length=10)
    occurred_at: datetime
    vendor_org_id: UUID
    customer_org_id: UUID
    agent_id: UUID
    deployment_id: UUID
    execution_id: UUID | None = None
    trace_id: UUID | None = None
    span_id: UUID | None = None
    parent_span_id: UUID | None = None
    span_kind: str | None = Field(default=None, max_length=40)
    kind: EventKind
    name: str = Str200
    severity: Literal["debug", "info", "warning", "error", "critical"] = "info"
    status: str | None = Field(default=None, max_length=40)
    duration_ms: float | None = Field(default=None, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = Field(default=None, max_length=100)


class IngestBatch(Strict):
    events: list[IngestEvent] = Field(min_length=1, max_length=500)


# ---- Policies (§2), approvals, actions (§3, §4) ----------------------------
class PolicyDeclaration(Lenient):
    id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{1,40}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.\-]+)?$")
    description: str = Field(min_length=1, max_length=2000)
    enforcement_point: str = Field(min_length=1, max_length=100)
    scope: str = Field(default="production", max_length=50)
    owner: str = Field(default="", max_length=200)
    tools: list[str] = Field(min_length=1, max_length=50)
    artifact_hash: str = Digest
    source_file: str = Field(default="", max_length=200)


class PolicyRegistration(Lenient):
    installation_id: UUID | None = None
    deployment_id: UUID | None = None
    policies: list[PolicyDeclaration] = Field(min_length=1, max_length=50)


class PolicySubmitIn(Strict):
    installation_id: UUID
    note: str | None = Field(default=None, max_length=2000)


class DecisionIn(Strict):
    decision: Literal["approve", "reject", "revoke"]
    reason: str | None = Field(default=None, max_length=2000)


GateDecision = Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"]


class LocalPolicyResult(Lenient):
    policy_id: str = Field(max_length=50)
    version: str = Field(max_length=50)
    artifact_hash: str = Field(max_length=80)
    decision: GateDecision
    reason_code: str = Field(default="", max_length=200)


class AuthorizeIn(Lenient):
    action_id: UUID | None = None
    agent_id: UUID
    deployment_id: UUID
    installation_id: UUID
    customer_org_id: UUID
    environment: str = Field(max_length=20)
    execution_id: UUID
    trace_id: UUID
    span_id: UUID | None = None
    tool: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,99}$")
    risk: Literal["low", "high"] = "high"
    arguments_hash: str = Digest
    arguments: Any = None  # redacted, display only; binding is arguments_hash
    local_decision: GateDecision
    policies: list[LocalPolicyResult] = Field(default_factory=list, max_length=20)


class ActionResultIn(Lenient):
    phase: Literal["executed", "verified"] = "executed"
    grant_id: UUID | None = None
    nonce: str | None = Field(default=None, max_length=200)
    outcome: Literal["succeeded", "failed", "verified", "verification_failed"]
    executed_at: datetime | None = None
    verified_at: datetime | None = None
    error_class: str | None = Field(default=None, max_length=100)
    result_metadata: dict[str, Any] = Field(default_factory=dict)


# ---- Builds, evaluations, releases ----------------------------------------
class BuildIn(Strict):
    version: str = Field(min_length=1, max_length=50)
    source_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    artifact_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class EvalCaseIn(Strict):
    case_key: str = Str200
    mandatory: bool = True
    status: Literal["passed", "failed", "error", "skipped"]
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)
    trace_id: UUID | None = None


class EvalRunIn(Strict):
    build: BuildIn
    suite_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{1,80}$")
    suite_description: str = Field(min_length=1, max_length=500)
    mandatory: bool = True
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cases: list[EvalCaseIn] = Field(min_length=1, max_length=1000)


class ReleaseEvaluateIn(Strict):
    installation_id: UUID
    build_version: str = Field(min_length=1, max_length=50)
    artifact_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class IntegrationToggleIn(Strict):
    organization_id: UUID
    enabled: bool


class KeewanoQueryIn(Strict):
    installation_id: UUID
    question: str = Field(min_length=3, max_length=500)


class DemoMessageIn(Strict):
    message: str = Field(min_length=1, max_length=2000)
    scenario: Literal["healthy", "degraded", "approval", "faulty"] = "degraded"
