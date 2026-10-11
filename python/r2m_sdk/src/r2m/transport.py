"""HTTP transport to the R2M platform: synchronous control calls + buffered event ingest.

Control calls (registration, authorize, action result) are synchronous and raise on
failure so the caller can fail closed. Trace events are buffered and shipped in
batches to ``POST /api/v1/ingest/events``; event_ids are fixed at creation so retries
are idempotent on the server (``ON CONFLICT DO NOTHING``).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from typing import Any

import httpx

from .types import TransportError

log = logging.getLogger("r2m.transport")

API_PREFIX = "/api/v1"
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class Transport:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 5.0,
        max_retries: int = 3,
        backoff_s: float = 0.2,
        batch_size: int = 100,
        flush_interval_s: float = 0.5,
        max_buffer: int = 10_000,
        background: bool = True,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not token:
            raise TransportError("SDK ingest token is required")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}", "User-Agent": "r2m-sdk/0.1.0"},
            transport=http_transport,
        )
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max_buffer)
        self._send_lock = threading.Lock()
        self.dropped_events = 0
        self.failed_batches: list[list[dict[str, Any]]] = []
        self._background = background
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        if background:
            self._worker = threading.Thread(target=self._run, name="r2m-transport", daemon=True)
            self._worker.start()

    # ---- control plane -------------------------------------------------
    def request(self, method: str, path: str, json: Any = None) -> dict[str, Any]:
        url = f"{API_PREFIX}{path}"
        request_id = str(uuid.uuid4())
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.request(method, url, json=json, headers={"X-Request-ID": request_id})
            except httpx.TransportError as exc:
                last_exc = exc
            else:
                if resp.status_code < 400:
                    return resp.json() if resp.content else {}
                if resp.status_code not in _RETRYABLE_STATUS:
                    code = None
                    try:
                        code = resp.json().get("code")
                    except Exception:
                        pass
                    raise TransportError(
                        f"{method} {path} -> {resp.status_code}", status_code=resp.status_code, code=code
                    )
                last_exc = TransportError(f"{method} {path} -> {resp.status_code}", status_code=resp.status_code)
            if attempt < self._max_retries:
                time.sleep(self._backoff_s * (2**attempt))
        raise TransportError(f"{method} {path} failed after retries: {type(last_exc).__name__}") from last_exc

    # ---- data plane ----------------------------------------------------
    def emit(self, event: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped_events += 1
            log.warning("r2m event buffer full; dropped event kind=%s", event.get("kind"))

    def flush(self, timeout_s: float = 5.0) -> bool:
        """Send everything buffered. Returns True if the buffer drained without failures."""
        deadline = time.monotonic() + timeout_s
        ok = True
        while time.monotonic() < deadline:
            batch = self._drain(self._batch_size)
            if not batch:
                break
            ok = self._send_batch(batch) and ok
        return ok and self._queue.empty()

    def close(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=2)
        self.flush()
        self._client.close()

    def _drain(self, n: int) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        while len(batch) < n:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def _send_batch(self, batch: list[dict[str, Any]]) -> bool:
        with self._send_lock:
            try:
                self.request("POST", "/ingest/events", {"events": batch})
                return True
            except TransportError as exc:
                # Keep the batch for a later retry instead of silently losing it.
                log.warning("r2m ingest failed (%s); retaining %d events", exc, len(batch))
                self.failed_batches.append(batch)
                return False

    def retry_failed(self) -> bool:
        pending, self.failed_batches = self.failed_batches, []
        return all([self._send_batch(b) for b in pending])

    def _run(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self._flush_interval_s)
            batch = self._drain(self._batch_size)
            if batch:
                self._send_batch(batch)
