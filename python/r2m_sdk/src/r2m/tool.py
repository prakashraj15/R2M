"""Protected tool decorator: the SDK's guarded action path (spec §4, §6).

Guarded tool call, in order:
  1. bind + canonically hash the arguments
  2. fail closed if any bound policy is not registered with a matching hash
  3. evaluate code-owned policies locally
  4. ``POST /actions/authorize`` (unreachable platform => DENY)
  5. combine: local DENY can never be relaxed; local REQUIRE_APPROVAL is only satisfied
     by a server ALLOW that carries an approved exact-action approval
  6. verify the single-use, action-bound grant
  7. execute, then report the real outcome to ``POST /actions/{id}/result``

Unguarded tools are traced with ``coverage=observed`` only: R2M saw the call but
cannot prove the host couldn't have made it without the SDK.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from . import context as _ctx
from .approvals import ActionGrant, arguments_hash
from .policy import Policy, PolicyContext
from .redact import redact
from .tracing import Span, iso, utcnow
from .types import (ApprovalRequired, Coverage, Decision, EventKind, GrantInvalid, PolicyActivationError,
                    PolicyDenied, Risk, Severity, SpanKind, Status, TransportError)

if TYPE_CHECKING:
    from .client import R2MClient

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class ToolSpec:
    key: str
    risk: Risk
    policies: tuple[Policy, ...]
    guarded: bool
    component: str | None = None


class _ToolGate:
    def __init__(self, client: "R2MClient", spec: ToolSpec, fn: Callable[..., Any]):
        self.client = client
        self.spec = spec
        self.sig = inspect.signature(fn)

    def bind(self, args: tuple, kwargs: dict) -> dict[str, Any]:
        bound = self.sig.bind(*args, **kwargs)
        bound.apply_defaults()
        return {k: v for k, v in bound.arguments.items() if k not in ("self", "cls")}

    def open_span(self, arguments: dict[str, Any], args_hash: str) -> Span:
        return self.client.span(f"tool:{self.spec.key}", SpanKind.TOOL, {
            "tool": self.spec.key,
            "risk": self.spec.risk.value,
            "coverage": (Coverage.ENFORCED if self.spec.guarded else Coverage.OBSERVED).value,
            "arguments_hash": args_hash,
            "arguments": redact(arguments),
            "component": self.spec.component or self.spec.key,
        })

    # ---- authorization -------------------------------------------------
    def _decision_event(self, span: Span, outcome: Decision, reason_codes: tuple[str, ...], *,
                        decision_id: str | None = None, action_id: str | None = None,
                        revision_ids: tuple[str, ...] = (), local: list[dict[str, Any]] | None = None) -> None:
        span.set_attributes(authorization_outcome=outcome.value, tool_action_id=action_id, decision_id=decision_id)
        self.client._emit(
            EventKind.POLICY_DECISION, f"policy:{self.spec.key}", span_id=span.id,
            severity=Severity.WARNING if outcome != Decision.ALLOW else Severity.INFO,
            status=outcome.value.lower(),
            attributes={
                "tool": self.spec.key,
                "authorization_outcome": outcome.value,
                "reason_codes": list(reason_codes),
                "decision_id": decision_id,
                "tool_action_id": action_id,
                "policy_revision_id": revision_ids[0] if len(revision_ids) == 1 else None,
                "policy_revision_ids": list(revision_ids),
                "policies": [{"id": p.id, "version": p.version, "artifact_hash": p.artifact_hash}
                             for p in self.spec.policies],
                "local_results": local or [],
            },
        )

    def authorize(self, span: Span, arguments: dict[str, Any], args_hash: str) -> ActionGrant | None:
        if not self.spec.guarded:
            return None
        key = self.spec.key
        execution = _ctx.current_execution()
        if execution is None:
            self._decision_event(span, Decision.DENY, ("NO_EXECUTION_CONTEXT",))
            raise PolicyDenied(key, ("NO_EXECUTION_CONTEXT",))

        for p in self.spec.policies:
            if not self.client.policy_verified(p):
                codes = (f"POLICY_NOT_ACTIVE:{p.id}",)
                self._decision_event(span, Decision.DENY, codes)
                raise PolicyActivationError(key, codes)

        ctx = PolicyContext(tool=key, arguments=arguments, environment=self.client.environment,
                            customer_org_id=self.client.customer_org_id, execution_id=execution.execution_id)
        local = [(p, p.evaluate(ctx)) for p in self.spec.policies]
        local_decision = Decision.strictest(Decision.ALLOW, *(r.decision for _, r in local))
        local_payload = [{"policy_id": p.id, "version": p.version, "artifact_hash": p.artifact_hash,
                          "decision": r.decision.value, "reason_code": r.reason_code} for p, r in local]

        try:
            auth = self.client.authorize_action(
                tool=key, risk=self.spec.risk, arguments_hash=args_hash, arguments=redact(arguments),
                local_decision=local_decision, local_results=local_payload, span_id=span.id,
                action_id=_ctx.resumed_action_id(),
            )
        except TransportError as exc:
            codes = ("AUTHORIZATION_UNAVAILABLE",) + ((exc.code,) if exc.code else ())
            self._decision_event(span, Decision.DENY, codes, local=local_payload)
            raise PolicyDenied(key, codes) from exc

        local_codes = tuple(r.reason_code for _, r in local if r.decision != Decision.ALLOW)
        codes = tuple(dict.fromkeys(local_codes + auth.reason_codes))
        if Decision.DENY in (local_decision, auth.decision):
            final = Decision.DENY
        elif auth.decision == Decision.ALLOW and (
                local_decision == Decision.ALLOW or auth.raw.get("approval_status") == "approved"):
            final = Decision.ALLOW
        else:
            final = Decision.REQUIRE_APPROVAL

        self._decision_event(span, final, codes, decision_id=auth.decision_id, action_id=auth.action_id,
                             revision_ids=auth.policy_revision_ids, local=local_payload)
        if final == Decision.DENY:
            raise PolicyDenied(key, codes, action_id=auth.action_id, decision_id=auth.decision_id)
        if final == Decision.REQUIRE_APPROVAL:
            raise ApprovalRequired(key, codes, action_id=auth.action_id, approval_id=auth.approval_id,
                                   decision_id=auth.decision_id)
        if not auth.grant:
            raise GrantInvalid(key, ("GRANT_MISSING",), action_id=auth.action_id, decision_id=auth.decision_id)
        grant = ActionGrant.from_dict(auth.grant)
        self.client.grant_verifier.verify(
            grant, tool=key, args_hash=args_hash, execution_id=execution.execution_id,
            customer_org_id=self.client.customer_org_id, deployment_id=self.client.deployment_id or "",
            action_id=auth.action_id,
        )
        return grant

    # ---- outcome -------------------------------------------------------
    def report(self, span: Span, grant: ActionGrant | None, args_hash: str, result: Any,
               exc: BaseException | None, executed_at: str) -> None:
        outcome = "failed" if exc else "succeeded"
        metadata = redact(result) if isinstance(result, dict) else {"result_type": type(result).__name__}
        if grant is not None:
            try:
                self.client.report_action_result(grant.action_id, {
                    "grant_id": grant.grant_id,
                    "nonce": grant.nonce,
                    "phase": "executed",
                    "outcome": outcome,
                    "executed_at": executed_at,
                    "error_class": type(exc).__name__ if exc else None,
                    "result_metadata": metadata,
                })
            except TransportError as rexc:
                # The action already happened; never hide it. Surface as an error event.
                self.client._emit(EventKind.ERROR, "action_result_report_failed", span_id=span.id,
                                  severity=Severity.ERROR, status="error",
                                  attributes={"tool_action_id": grant.action_id, "error_class": type(rexc).__name__})
        self.client._emit(
            EventKind.TOOL_CALL, f"tool:{self.spec.key}", span_id=span.id,
            severity=Severity.ERROR if exc else Severity.INFO, status=Status.ERROR.value if exc else Status.OK.value,
            attributes={
                "tool": self.spec.key,
                "risk": self.spec.risk.value,
                "coverage": (Coverage.ENFORCED if grant else Coverage.OBSERVED).value,
                "arguments_hash": args_hash,
                "tool_action_id": grant.action_id if grant else None,
                "outcome": outcome,
                "error_class": type(exc).__name__ if exc else None,
                "result": metadata,
            },
        )


def build_tool(client: "R2MClient", fn: F, spec: ToolSpec) -> F:
    gate = _ToolGate(client, spec, fn)

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def awrapper(*args: Any, **kwargs: Any) -> Any:
            arguments = gate.bind(args, kwargs)
            args_hash = arguments_hash(arguments)
            async with gate.open_span(arguments, args_hash) as span:
                grant = await asyncio.to_thread(gate.authorize, span, arguments, args_hash)
                executed_at = iso(utcnow())
                try:
                    result = await fn(*args, **kwargs)
                except Exception as exc:
                    await asyncio.to_thread(gate.report, span, grant, args_hash, None, exc, executed_at)
                    raise
                await asyncio.to_thread(gate.report, span, grant, args_hash, result, None, executed_at)
                return result
        awrapper.r2m_tool = spec  # type: ignore[attr-defined]
        return awrapper  # type: ignore[return-value]

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        arguments = gate.bind(args, kwargs)
        args_hash = arguments_hash(arguments)
        with gate.open_span(arguments, args_hash) as span:
            grant = gate.authorize(span, arguments, args_hash)
            executed_at = iso(utcnow())
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                gate.report(span, grant, args_hash, None, exc, executed_at)
                raise
            gate.report(span, grant, args_hash, result, None, executed_at)
            return result
    wrapper.r2m_tool = spec  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]
