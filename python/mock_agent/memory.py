"""Conversation memory: the pending approval-gated action per customer org.

``handle_message`` is stateless between calls, so the action awaiting a reviewer is kept here,
keyed by customer org. Process-local by design (demo); losing it only means the user must ask
again. Reads/writes are traced as ``memory`` spans on the conversation-memory node.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from r2m import SpanKind

if TYPE_CHECKING:
    from r2m import R2MClient

COMPONENT = "conversation-memory"
_STORE: dict[str, dict[str, Any]] = {}
_HISTORY: dict[tuple[str, str, str], list[dict[str, str]]] = {}
_FINGERPRINT: dict[tuple[str, str, str], str] = {}
MAX_HISTORY_MESSAGES = 12
_LOCK = threading.Lock()


class ConversationMemory:
    def __init__(self, client: "R2MClient", customer_org_id: str, actor: str | None = None):
        self._client = client
        self._key = customer_org_id  # pending approvals are shared within the customer org
        self._actor = actor or "anonymous"  # conversations are per person

    def peek(self, world_fingerprint: str | None = None) -> dict[str, Any] | None:
        """Untraced lookup, for deciding whether to resume before any execution is open.

        A pending action saved under a different world state (e.g. before a scenario reset, which also
        expires the approval server-side) is stale and is dropped. Approving does not change the world.
        """
        with _LOCK:
            item = _STORE.get(self._key)
            if item and world_fingerprint is not None and item.get("world_fingerprint") not in (None, world_fingerprint):
                _STORE.pop(self._key, None)
                item = None
        return dict(item) if item else None

    def pending(self) -> dict[str, Any] | None:
        with self._client.span("memory.read_pending", SpanKind.MEMORY, component=COMPONENT) as span:
            with _LOCK:
                item = _STORE.get(self._key)
            span.set_attribute("hit", item is not None)
            return dict(item) if item else None

    def save_pending(self, item: dict[str, Any]) -> None:
        with self._client.span("memory.save_pending", SpanKind.MEMORY, component=COMPONENT,
                               attributes={"tool": item.get("tool"), "action_id": item.get("action_id")}):
            with _LOCK:
                _STORE[self._key] = dict(item)

    def clear_pending(self) -> None:
        with self._client.span("memory.clear_pending", SpanKind.MEMORY, component=COMPONENT):
            with _LOCK:
                _STORE.pop(self._key, None)


    def history(self, scenario: str, world_fingerprint: str | None = None) -> list[dict[str, str]]:
        """Recent user/assistant text for the live model (already redacted when stored).

        History is only valid for the world it describes: if the service changed since the last turn
        (scenario reset, another user's action), the old conversation is dropped so the model can't
        talk about a state that no longer exists.
        """
        with _LOCK:
            key = (self._key, self._actor, scenario)
            if world_fingerprint is not None and _FINGERPRINT.get(key) != world_fingerprint:
                _HISTORY.pop(key, None)
            return list(_HISTORY.get(key, []))

    def append_history(self, scenario: str, user: str, assistant: str,
                       world_fingerprint: str | None = None) -> None:
        with _LOCK:
            key = (self._key, self._actor, scenario)
            items = _HISTORY.setdefault(key, [])
            items += [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]
            del items[:-MAX_HISTORY_MESSAGES]
            if world_fingerprint is not None:
                _FINGERPRINT[key] = world_fingerprint


def reset_all() -> None:
    """Tests/evals only."""
    with _LOCK:
        _STORE.clear()
        _HISTORY.clear()
        _FINGERPRINT.clear()
