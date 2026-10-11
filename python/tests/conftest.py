"""Platform tests run against a real, disposable Postgres: TEST_DATABASE_URL (its public schema is wiped)."""
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "python"), str(ROOT / "scripts")]

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to a disposable database to run platform tests", allow_module_level=True)

os.environ.update({
    "APP_ENV": "demo", "DATABASE_URL": os.environ["TEST_DATABASE_URL"],
    "DATABASE_SSL_MODE": os.environ.get("TEST_DATABASE_SSL_MODE", "disable"),
    "SESSION_SIGNING_KEY": "test-signing-key-0123456789abcdef0123", "SDK_INGEST_TOKEN": "test-sdk-token-0123456789abcdef01234",
    "R2M_INTERNAL_API_URL": "http://127.0.0.1:8000", "KEEWANO_ENABLED": "false",
})


async def reset_db() -> None:
    """Wipe the disposable test database, apply migrations and seed demo data."""
    import asyncpg
    from init_db import migrate
    from seed_demo import seed
    conn = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await migrate(conn)
        await seed(conn)
    finally:
        await conn.close()
