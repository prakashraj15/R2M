"""asyncpg pool over verified TLS, running as the RLS-restricted r2m_app role. Raw parameterized SQL only.

Row-level security (db/migrations/0003) reads the caller's scope from session settings. Every pooled
connection starts with an empty scope (sees no tenant rows); auth dependencies apply the caller's scope to
the request connection and record it in `current_scope`, so extra connections borrowed by the same request
(e.g. parallel dashboard queries) get it too. Releasing a connection clears its scope.
"""
import json
import ssl
from contextvars import ContextVar
from dataclasses import dataclass

import asyncpg

from .config import Settings

APP_ROLE = "r2m_app"


@dataclass(frozen=True)
class Scope:
    installations: tuple = ()
    orgs: tuple = ()
    bypass: bool = False  # platform-internal work only (outbox worker, SDK registration)


BYPASS = Scope(bypass=True)
current_scope: ContextVar[Scope | None] = ContextVar("r2m_scope", default=None)


def ssl_context(settings: Settings) -> ssl.SSLContext | bool:
    if settings.database_ssl_mode == "disable":
        return False  # config.py only allows this for loopback hosts
    ctx = ssl.create_default_context(cafile=settings.database_ca_cert)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _dumps(value) -> str:
    return json.dumps(value, default=str)  # UUIDs/datetimes in JSON bodies


async def apply_scope(conn: asyncpg.Connection, scope: Scope) -> None:
    await conn.execute("SELECT r2m_set_scope($1::uuid[], $2::uuid[], $3)",
                       list(scope.installations), list(scope.orgs), scope.bypass)


async def _init_connection(conn: asyncpg.Connection) -> None:
    for typename in ("json", "jsonb"):
        await conn.set_type_codec(typename, encoder=_dumps, decoder=json.loads, schema="pg_catalog")
    await conn.execute(f"SET ROLE {APP_ROLE}")  # non-owner, no BYPASSRLS: tenant policies always apply


async def _on_acquire(conn: asyncpg.Connection) -> None:
    scope = current_scope.get()
    if scope is not None:
        await apply_scope(conn, scope)


async def _on_release(conn: asyncpg.Connection) -> None:
    # Replaces asyncpg's RESET ALL (which would also drop the role); same round trip, keeps r2m_app.
    await conn.execute("SELECT r2m_set_scope('{}', '{}', false)")


async def create_pool(settings: Settings, **kwargs) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        settings.database_url, ssl=ssl_context(settings), init=_init_connection, setup=_on_acquire,
        reset=_on_release,
        # Warm connections: a remote Aiven TLS handshake costs several round trips.
        min_size=5, max_size=10, command_timeout=30, **kwargs,
    )
