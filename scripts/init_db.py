"""Apply db/migrations/*.sql in order, idempotently. Each file manages its own transaction and version row."""
import asyncio
import pathlib
import sys

import asyncpg

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))
from r2m_platform.config import load_settings  # noqa: E402
from r2m_platform.database import ssl_context  # noqa: E402

MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent / "db" / "migrations"
LOCK_KEY = 72_026_101  # arbitrary constant: serialises concurrent init_db runs


async def migrate(conn) -> list[str]:
    await conn.execute("SELECT pg_advisory_lock($1)", LOCK_KEY)
    try:
        exists = await conn.fetchval("SELECT to_regclass('public.schema_migrations') IS NOT NULL")
        applied = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")} if exists else set()
        done = []
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.stem not in applied:
                await conn.execute(path.read_text())
                done.append(path.stem)
        return done
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)


async def main() -> None:
    settings = load_settings()
    conn = await asyncpg.connect(settings.database_url, ssl=ssl_context(settings))
    try:
        done = await migrate(conn)
        print("applied:", ", ".join(done) if done else "nothing (up to date)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
