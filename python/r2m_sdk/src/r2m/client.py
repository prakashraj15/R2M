"""R2M client: configuration, agent/policy registration, executions and event emission."""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Callable, Iterable, TypeVar

import httpx

from . import context as _ctx
from .approvals import GrantVerifier
from .model import ModelCall
from .policy import Policy
from .redact import redact
from .tool import ToolSpec, build_tool
from .tracing import Span, iso, traced, utcnow
from .transport import Transport
from .types import (SCHEMA_VERSION, ApprovalRequired, AuthorizationResult, ConfigurationError, CostSource, Decision,
                    EventKind, Risk, Severity, SpanKind, Status)

log = logging.getLogger("r2m")
SDK_VERSION = "0.1.0"
F = TypeVar("F", bound=Callable[..., Any])


class ExecutionScope:
    """One agent run. ``with client.execution("degraded") as run: ...``

    If an :class:`ApprovalRequired` escapes, or ``suspend()`` is called, the execution
    is left open (``running``) so it can be resumed after the reviewer decides.
    """

    def __init__(self, client: "R2MClient", scenario: str | None, execution_id: str | None,
                 trace_id: str | None, metadata: dict[str, Any] | None, resume: bool):
        self._client = client
        exec_id = execution_id or str(uuid.uuid4())
        self.context = _ctx.ExecutionContext(execution_id=exec_id, trace_id=trace_id or exec_id, scenario=scenario)
        self.metadata = metadata or {}
        self.resume = resume
        self.status = "completed"
        self._suspended = False
        self._cm = None

    @property
    def execution_id(self) -> str:
        return self.context.execution_id

    @property
    def trace_id(self) -> str:
        return self.context.trace_id

    def suspend(self) -> None:
        self._suspended = True

    def fail(self) -> None:
        self.status = "failed"

    def _start(self) -> "ExecutionScope":
        if not self._client.deployment_id:
            raise ConfigurationError("deployment_id is not set; call register_agent() or pass it explicitly")
        self._cm = _ctx.use_execution(self.context)
        self._cm.__enter__()
        self._client._emit(EventKind.EXECUTION_STARTED, "execution", status=Status.RUNNING.value, attributes={
            "scenario": self.context.scenario, "resumed": self.resume, "metadata": self.metadata})
        return self

    def _finish(self, exc: BaseException | None) -> None:
        if isinstance(exc, ApprovalRequired):
            self._suspended = True
        elif exc is not None:
            self.status = "failed"
        if not self._suspended:
            self._client._emit(
                EventKind.EXECUTION_ENDED, "execution",
                status=self.status, severity=Severity.ERROR if self.status == "failed" else Severity.INFO,
                attributes={"scenario": self.context.scenario,
                            "error_class": type(exc).__name__ if exc else None})
        self._cm.__exit__(None, None, None)

    def __enter__(self) -> "ExecutionScope":
        return self._start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self._finish(exc)

    async def __aenter__(self) -> "ExecutionScope":
        return self._start()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._finish(exc)


class R2MClient:
    def __init__(
        self,
        *,
        token: str,
        agent_slug: str,
        vendor_org_id: str,
        customer_org_id: str,
        environment: str = "demo",
        base_url: str = "http://127.0.0.1:8000",
        agent_id: str | None = None,
        installation_id: str | None = None,
        deployment_id: str | None = None,
        grant_key: str | None = None,
        background: bool = True,
        transport: Transport | None = None,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.agent_slug = agent_slug
        self.vendor_org_id = vendor_org_id
        self.customer_org_id = customer_org_id
        self.environment = environment
        self.agent_id = agent_id
        self.installation_id = installation_id
        self.deployment_id = deployment_id
        self.transport = transport or Transport(base_url, token, background=background, http_transport=http_transport)
        self.grant_verifier = GrantVerifier(grant_key or token)
        self._policies: dict[str, Policy] = {}
        self._verified_hashes: dict[str, str] = {}
        self._revision_ids: dict[str, str] = {}

    @classmethod
    def from_env(cls, **overrides: Any) -> "R2MClient":
        env = os.environ
        cfg: dict[str, Any] = {
            "base_url": env.get("R2M_INTERNAL_API_URL", "http://127.0.0.1:8000"),
            "token": env.get("SDK_INGEST_TOKEN", ""),
            "grant_key": env.get("R2M_GRANT_SIGNING_KEY") or None,
            "agent_slug": env.get("R2M_AGENT_SLUG", ""),
            "vendor_org_id": env.get("R2M_VENDOR_ORG_ID", ""),
            "customer_org_id": env.get("R2M_CUSTOMER_ORG_ID", ""),
            "environment": env.get("R2M_ENVIRONMENT", "demo"),
        }
        cfg.update(overrides)
        missing = [k for k in ("token", "agent_slug", "vendor_org_id", "customer_org_id") if not cfg.get(k)]
        if missing:
            raise ConfigurationError(f"missing R2M SDK configuration: {', '.join(missing)}")
        return cls(**cfg)

    # ---- registration --------------------------------------------------
    def register_agent(self, *, name: str, description: str = "", build_version: str, source_digest: str,
                       artifact_digest: str, components: Iterable[dict[str, Any]] = (),
                       edges: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
        resp = self.transport.request("POST", "/agents", {
            "slug": self.agent_slug,
            "name": name,
            "description": description,
            "sdk_version": SDK_VERSION,
            "vendor_org_id": self.vendor_org_id,
            "customer_org_id": self.customer_org_id,
            "environment": self.environment,
            "build": {"version": build_version, "source_digest": source_digest, "artifact_digest": artifact_digest},
            "topology": {"components": list(components), "edges": list(edges)},
        })
        self.agent_id = resp["agent_id"]
        self.installation_id = resp.get("installation_id")
        self.deployment_id = resp.get("deployment_id")
        return resp

    def register_policies(self, *policies: Policy) -> list[dict[str, Any]]:
        if not self.agent_id:
            raise ConfigurationError("register_agent() first (agent_id unknown)")
        for p in policies:
            self._policies[p.id] = p
        resp = self.transport.request("POST", f"/agents/{self.agent_id}/policies/register", {
            "installation_id": self.installation_id,
            "deployment_id": self.deployment_id,
            "policies": [p.manifest() for p in policies],
        })
        results = resp.get("policies", [])
        for r in results:
            local = self._policies.get(r.get("policy_id", ""))
            if local and r.get("artifact_hash") == local.artifact_hash and r.get("hash_matches", True):
                self._verified_hashes[local.id] = local.artifact_hash
                if r.get("revision_id"):
                    self._revision_ids[local.id] = r["revision_id"]
            elif local:
                self._verified_hashes.pop(local.id, None)
                log.warning("policy %s hash not confirmed by platform; guarded tools will fail closed", local.id)
        return results

    def policy_verified(self, p: Policy) -> bool:
        return self._verified_hashes.get(p.id) == p.artifact_hash

    # ---- instrumentation API ------------------------------------------
    def tool(self, key: str, *, risk: Risk | str = Risk.LOW, policies: Iterable[Policy] = (),
             guarded: bool | None = None, component: str | None = None) -> Callable[[F], F]:
        risk = Risk(risk)
        pols = tuple(policies)
        for p in pols:
            if key not in p.tools:
                raise ConfigurationError(f"policy {p.id} does not declare tool {key!r}")
        is_guarded = guarded if guarded is not None else (risk == Risk.HIGH or bool(pols))
        spec = ToolSpec(key=key, risk=risk, policies=pols, guarded=is_guarded, component=component)
        return lambda fn: build_tool(self, fn, spec)

    def span(self, name: str, kind: SpanKind = SpanKind.ORCHESTRATION,
             attributes: dict[str, Any] | None = None) -> Span:
        return Span(self, name, kind, attributes)

    def traced(self, name: str | None = None, kind: SpanKind = SpanKind.ORCHESTRATION) -> Callable[[F], F]:
        return traced(self, name, kind)

    def model_call(self, model: str, *, provider: str = "simulated", purpose: str | None = None,
                   cost_source: CostSource | None = None) -> ModelCall:
        return ModelCall(self, model, provider, purpose, cost_source)

    def execution(self, scenario: str | None = None, *, execution_id: str | None = None,
                  trace_id: str | None = None, metadata: dict[str, Any] | None = None,
                  resume: bool = False) -> ExecutionScope:
        return ExecutionScope(self, scenario, execution_id, trace_id, metadata, resume)

    resume_action = staticmethod(_ctx.resume_action)

    def event(self, kind: EventKind, name: str, attributes: dict[str, Any] | None = None, *,
              severity: Severity = Severity.INFO, status: str | None = None) -> None:
        self._emit(kind, name, span_id=_ctx.current_span_id(), attributes=attributes or {},
                   severity=severity, status=status)

    def transition(self, from_state: str | None, to_state: str, **attributes: Any) -> None:
        self.event(EventKind.STATE_TRANSITION, f"{from_state or 'START'}->{to_state}",
                   {"from_state": from_state, "to_state": to_state, **attributes})

    def heartbeat(self, status: str = "ok", **attributes: Any) -> None:
        self._emit(EventKind.HEARTBEAT, "heartbeat", status=status, attributes=attributes)

    # ---- control-plane calls ------------------------------------------
    def authorize_action(self, *, tool: str, risk: Risk, arguments_hash: str, arguments: Any,
                         local_decision: Decision, local_results: list[dict[str, Any]], span_id: str | None,
                         action_id: str | None = None) -> AuthorizationResult:
        execution = _ctx.current_execution()
        resp = self.transport.request("POST", "/actions/authorize", {
            "action_id": action_id,
            "agent_id": self.agent_id,
            "deployment_id": self.deployment_id,
            "installation_id": self.installation_id,
            "customer_org_id": self.customer_org_id,
            "environment": self.environment,
            "execution_id": execution.execution_id if execution else None,
            "trace_id": execution.trace_id if execution else None,
            "span_id": span_id,
            "tool": tool,
            "risk": risk.value,
            "arguments_hash": arguments_hash,
            "arguments": arguments,
            "local_decision": local_decision.value,
            "policies": local_results,
        })
        return AuthorizationResult(
            decision=Decision(resp["decision"]),
            reason_codes=tuple(resp.get("reason_codes", ())),
            decision_id=resp.get("decision_id"),
            action_id=resp.get("action_id"),
            policy_revision_ids=tuple(resp.get("policy_revision_ids", ())),
            grant=resp.get("grant"),
            approval_id=resp.get("approval_id"),
            raw=resp,
        )

    def report_action_result(self, action_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.transport.request("POST", f"/actions/{action_id}/result", body)

    def report_verification(self, action_id: str, *, verified: bool, details: dict[str, Any] | None = None) -> None:
        """Record that the agent checked the action's real effect (separate from execution)."""
        self.report_action_result(action_id, {"phase": "verified", "outcome": "verified" if verified else
                                              "verification_failed", "verified_at": iso(utcnow()),
                                              "result_metadata": redact(details or {})})

    # ---- lifecycle -----------------------------------------------------
    def flush(self, timeout_s: float = 5.0) -> bool:
        return self.transport.flush(timeout_s)

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> "R2MClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---- internals -----------------------------------------------------
    def _emit(self, kind: EventKind, name: str, *, span_id: str | None = None, parent_span_id: str | None = None,
              span_kind: SpanKind | None = None, severity: Severity = Severity.INFO, status: str | None = None,
              duration_ms: float | None = None, attributes: dict[str, Any] | None = None,
              occurred_at: str | None = None) -> None:
        execution = _ctx.current_execution()
        self.transport.emit({
            "event_id": str(uuid.uuid4()),
            "schema_version": SCHEMA_VERSION,
            "occurred_at": occurred_at or iso(utcnow()),
            "vendor_org_id": self.vendor_org_id,
            "customer_org_id": self.customer_org_id,
            "agent_id": self.agent_id,
            "deployment_id": self.deployment_id,
            "execution_id": execution.execution_id if execution else None,
            "trace_id": execution.trace_id if execution else None,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "span_kind": span_kind.value if span_kind else None,
            "kind": kind.value,
            "name": name,
            "severity": severity.value,
            "status": status,
            "duration_ms": duration_ms,
            "attributes": redact(attributes or {}),
            "request_id": None,
        })

    def _finish_span(self, span: Span) -> None:
        assert span.started_at is not None
        self._emit(EventKind.SPAN, span.name, span_id=span.id, parent_span_id=span.parent_id, span_kind=span.kind,
                   severity=Severity.ERROR if span.status == Status.ERROR else Severity.INFO,
                   status=span.status.value, duration_ms=span.duration_ms, attributes=span.attributes,
                   occurred_at=iso(span.started_at))
