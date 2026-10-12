"""Set R2M sign-in passwords (scrypt hashes; the plaintext is never stored).

    python scripts/set_password.py ops@meridian.demo            # prompts (or reads one line from stdin)
    python scripts/set_password.py --generate --all > secrets/accounts.txt   # random password per user, printed once
"""
import argparse
import asyncio
import getpass
import pathlib
import secrets
import sys

import asyncpg

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))
from r2m_platform.auth import hash_password  # noqa: E402
from r2m_platform.config import get_settings  # noqa: E402
from r2m_platform.database import ssl_context  # noqa: E402

MIN_LENGTH = 12


def read_password(email: str) -> str:
    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass(f"New password for {email}: ")
    if first != getpass.getpass("Repeat: "):
        sys.exit("passwords do not match")
    return first


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("emails", nargs="*")
    ap.add_argument("--all", action="store_true", help="every user in the database")
    ap.add_argument("--generate", action="store_true", help="random passwords, printed as 'email password' lines")
    args = ap.parse_args()
    settings = get_settings()
    conn = await asyncpg.connect(settings.database_url, ssl=ssl_context(settings))
    try:
        emails = [r["email"] for r in await conn.fetch("SELECT email FROM users ORDER BY email")] if args.all else \
            [e.strip().lower() for e in args.emails]
        if not emails:
            sys.exit("name at least one email, or --all")
        for email in emails:
            password = secrets.token_urlsafe(18) if args.generate else read_password(email)
            if len(password) < MIN_LENGTH:
                sys.exit(f"password for {email} must be at least {MIN_LENGTH} characters")
            if await conn.execute("UPDATE users SET password_hash=$1 WHERE email=$2", hash_password(password), email) == "UPDATE 0":
                sys.exit(f"no such user: {email}")
            print(f"{email} {password}" if args.generate else f"password set for {email}", flush=True)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
