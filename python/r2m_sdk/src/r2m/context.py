"""contextvars-based propagation of the current execution, span and resumed action."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class ExecutionContext:
    execution_id: str
    trace_id: str
    scenario: str | None = None


_execution: ContextVar[ExecutionContext | None] = ContextVar("r2m_execution", default=None)
_span: ContextVar[str | None] = ContextVar("r2m_span", default=None)
_resume_action: ContextVar[str | None] = ContextVar("r2m_resume_action", default=None)


def current_execution() -> ExecutionContext | None:
    return _execution.get()


def current_span_id() -> str | None:
    return _span.get()


def resumed_action_id() -> str | None:
    return _resume_action.get()


@contextmanager
def use_execution(ctx: ExecutionContext) -> Iterator[ExecutionContext]:
    token = _execution.set(ctx)
    try:
        yield ctx
    finally:
        _execution.reset(token)


@contextmanager
def use_span(span_id: str) -> Iterator[str]:
    token = _span.set(span_id)
    try:
        yield span_id
    finally:
        _span.reset(token)


@contextmanager
def resume_action(action_id: str) -> Iterator[str]:
    """Re-attempt a previously REQUIRE_APPROVAL action once a reviewer approved it."""
    token = _resume_action.set(action_id)
    try:
        yield action_id
    finally:
        _resume_action.reset(token)
