"""asyncpg pool over verified TLS. Raw parameterized SQL only."""
import json
import ssl

import asyncpg

from .config import Settings


def ssl_context(settings: Settings) -> ssl.SSLContext | bool:
    if settings.database_ssl_mode == "disable":
        return False  # config.py only allows this for loopback hosts
    ctx = ssl.create_default_context(cafile=settings.database_ca_cert)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _dumps(value) -> str:
    return json.dumps(value, default=str)  # UUIDs/datetimes in JSON bodies


async def _init_connection(conn: asyncpg.Connection) -> None:
    for typename in ("json", "jsonb"):
        await conn.set_type_codec(typename, encoder=_dumps, decoder=json.loads, schema="pg_catalog")


async def create_pool(settings: Settings, **kwargs) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        settings.database_url, ssl=ssl_context(settings), init=_init_connection,
        # Warm connections: a remote Aiven TLS handshake costs several round trips.
        min_size=5, max_size=10, command_timeout=30, **kwargs,
    )
