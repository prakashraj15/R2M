"""Keewano insight queries, shared by the browser endpoint and the demo agent hook.

Advisory only: results are stored as untrusted data in insight_queries and never authorize actions.
"""
import asyncio
from uuid import UUID

import anyio.from_thread

from ..workers.event_outbox import adapter

TRUST = "untrusted advisory data"


async def run_insight_query(conn, inst, question: str, keewano_enabled: bool) -> dict:
    enabled = await conn.fetchval(
        "SELECT enabled FROM integration_configs WHERE organization_id=$1 AND provider='keewano'", inst["customer_org_id"])
    mod = adapter()
    if not (keewano_enabled and enabled and mod):
        return {"status": "unavailable", "message": "intelligence unavailable: Keewano integration disabled or not installed"}
    try:
        result = await asyncio.wait_for(mod.query(question, {"installation_id": str(inst["id"])}), timeout=20)
        status = "ok"
    except Exception as exc:
        result, status = {"error_class": type(exc).__name__}, "failed"
    qid = await conn.fetchval(
        """INSERT INTO insight_queries(installation_id, provider, prompt_summary, provider_request_id, response_summary, status, sample_count)
           VALUES ($1,'keewano',$2,$3,$4,$5,$6) RETURNING id""",
        inst["id"], question[:500], result.get("request_id"), result, status,
        result.get("sample_count") if isinstance(result.get("sample_count"), int) else None)
    return {"status": status, "insight_id": qid, "result": result, "trust": TRUST}


class AgentInsights:
    """Synchronous hook for the mock agent's worker thread: ``context["insights"].query(question)``."""

    def __init__(self, pool, installation: dict, keewano_enabled: bool):
        self._pool, self._inst, self._enabled = pool, dict(installation), keewano_enabled

    def query(self, question: str) -> dict:
        return anyio.from_thread.run(self._query, str(question)[:500])

    async def _query(self, question: str) -> dict:
        async with self._pool.acquire() as conn:
            out = await run_insight_query(conn, self._inst, question, self._enabled)
        if isinstance(out.get("insight_id"), UUID):
            out["insight_id"] = str(out["insight_id"])
        return out
