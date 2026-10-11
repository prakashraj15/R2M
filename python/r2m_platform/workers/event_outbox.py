"""Durable outbox mirroring selected R2M events to Keewano.

Backend owns durability and retry. The AI-owned adapter (services/keewano_adapter.py) owns mapping and
sanitization: `map_event(event: dict) -> dict | None` and `async send_events(payloads: list[dict]) -> None`.
"""
import asyncio
import importlib
import logging

from ..config import get_settings
from ..database import BYPASS, apply_scope

log = logging.getLogger("r2m.outbox")
MAX_ATTEMPTS = 8


def adapter():
    # import_module honours sys.modules first (tests swap in a fake adapter there).
    try:
        return importlib.import_module("r2m_platform.services.keewano_adapter")
    except ImportError:
        return None


async def enqueue(conn, customer_org_id, event_row: dict) -> None:
    """Call inside the ingest transaction so the outbox row commits atomically with the event."""
    mod = adapter()
    if mod is None or not get_settings().keewano_enabled:
        return
    integration_id = await conn.fetchval(
        "SELECT id FROM integration_configs WHERE organization_id=$1 AND provider='keewano' AND enabled",
        customer_org_id)
    if not integration_id:
        return
    payload = mod.map_event(event_row)
    if payload is not None:
        await conn.execute(
            """INSERT INTO integration_outbox(integration_id, source_event_id, payload) VALUES ($1,$2,$3)
               ON CONFLICT (integration_id, source_event_id) DO NOTHING""",
            integration_id, event_row["event_id"], payload)


async def drain_once(pool, batch_size: int = 50) -> int:
    mod = adapter()
    if mod is None:
        return 0
    async with pool.acquire() as conn:
        await apply_scope(conn, BYPASS)  # platform-internal: drains every tenant's outbox
        return await _drain(conn, mod, batch_size)


async def _drain(conn, mod, batch_size: int) -> int:
    async with conn.transaction():
        rows = await conn.fetch(
            """SELECT id, payload, attempts FROM integration_outbox
               WHERE state IN ('pending','failed') AND next_attempt_at <= now()
               ORDER BY next_attempt_at LIMIT $1 FOR UPDATE SKIP LOCKED""", batch_size)
        if not rows:
            return 0
        ids = [r["id"] for r in rows]
        try:
            await asyncio.wait_for(mod.send_events([r["payload"] for r in rows]), timeout=15)
        except Exception as exc:  # adapter failures must never break ingestion
            await conn.execute(
                """UPDATE integration_outbox SET attempts = attempts + 1, last_error_class = $2,
                   state = CASE WHEN attempts + 1 >= $3 THEN 'dead' ELSE 'failed' END,
                   next_attempt_at = now() + make_interval(secs => least(300, 5 * power(2, attempts)))
                   WHERE id = ANY($1::uuid[])""", ids, type(exc).__name__, MAX_ATTEMPTS)
            log.warning("keewano outbox send failed: %s", type(exc).__name__)
            return 0
        await conn.execute("UPDATE integration_outbox SET state='sent', attempts=attempts+1 WHERE id = ANY($1::uuid[])", ids)
        await conn.execute(
            """UPDATE integration_configs SET last_success_at = now() WHERE id IN
               (SELECT DISTINCT integration_id FROM integration_outbox WHERE id = ANY($1::uuid[]))""", ids)
        return len(ids)


async def run_forever(pool, interval: float = 5.0) -> None:
    while True:
        try:
            if await drain_once(pool) == 0:
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("outbox worker iteration failed")
            await asyncio.sleep(interval)
