"""Sync/async spans with parent propagation and exception capture."""
from __future__ import annotations

import functools
import inspect
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from . import context as _ctx
from .types import ApprovalRequired, PolicyDenied, SpanKind, Status
from .usage import Stopwatch

if TYPE_CHECKING:
    from .client import R2MClient

F = TypeVar("F", bound=Callable[..., Any])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class Span:
    """A timed unit of work. Usable as ``with`` or ``async with``.

    Emitted to the platform once, on exit, as a ``span`` event carrying start time,
    duration, status and redacted attributes.
    """

    def __init__(self, client: "R2MClient", name: str, kind: SpanKind, attributes: dict[str, Any] | None = None):
        self._client = client
        self.id = str(uuid.uuid4())
        self.name = name
        self.kind = kind
        self.attributes: dict[str, Any] = dict(attributes or {})
        self.parent_id: str | None = None
        self.status = Status.OK
        self.started_at: datetime | None = None
        self.duration_ms: float | None = None
        self._sw: Stopwatch | None = None
        self._token = None

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def set_attributes(self, **attrs: Any) -> None:
        self.attributes.update(attrs)

    def set_status(self, status: Status) -> None:
        self.status = status

    def _start(self) -> "Span":
        self.parent_id = _ctx.current_span_id()
        self.started_at = utcnow()
        self._sw = Stopwatch()
        self._token = _ctx._span.set(self.id)
        return self

    def _finish(self, exc: BaseException | None) -> None:
        assert self._sw is not None
        self.duration_ms = self._sw.elapsed_ms()
        _ctx._span.reset(self._token)
        if isinstance(exc, ApprovalRequired):
            self.status = Status.PENDING_APPROVAL
        elif isinstance(exc, PolicyDenied):
            self.status = Status.DENIED  # an intended deny is not a system failure
        elif exc is not None:
            self.status = Status.ERROR
            self.attributes["error_class"] = type(exc).__name__
        self._client._finish_span(self)

    def __enter__(self) -> "Span":
        return self._start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self._finish(exc)

    async def __aenter__(self) -> "Span":
        return self._start()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._finish(exc)


def traced(client: "R2MClient", name: str | None = None, kind: SpanKind = SpanKind.ORCHESTRATION) -> Callable[[F], F]:
    """Decorator wrapping a sync or async function in a span."""

    def wrap(fn: F) -> F:
        span_name = name or fn.__qualname__
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                async with client.span(span_name, kind):
                    return await fn(*args, **kwargs)
            return awrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with client.span(span_name, kind):
                return fn(*args, **kwargs)
        return wrapper  # type: ignore[return-value]

    return wrap
