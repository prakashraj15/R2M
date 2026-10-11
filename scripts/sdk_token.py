"""Issue, list or revoke per-customer SDK tokens (scoped to one vendor + customer pair).

    python scripts/sdk_token.py issue --vendor atlas-applied-ai --customer meridian-financial --label run-evals
    python scripts/sdk_token.py list
    python scripts/sdk_token.py revoke <credential-id>

The token is printed once and is derivable only with SDK_TOKEN_SECRET; nothing secret is stored in the database.
"""
import argparse
import asyncio
import pathlib
import sys
from uuid import UUID

import asyncpg

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))
from r2m_platform.auth import issue_sdk_credential  # noqa: E402
from r2m_platform.config import load_settings  # noqa: E402
from r2m_platform.database import ssl_context  # noqa: E402


async def main(args) -> None:
    settings = load_settings()
    conn = await asyncpg.connect(settings.database_url, ssl=ssl_context(settings))
    try:
        if args.cmd == "issue":
            ids = await conn.fetchrow(
                """SELECT v.id AS vendor, c.id AS customer FROM organizations v, organizations c
                   JOIN vendor_customer_links l ON l.customer_org_id = c.id
                   WHERE v.slug=$1 AND c.slug=$2 AND l.vendor_org_id = v.id AND l.status='active'""",
                args.vendor, args.customer)
            if not ids:
                sys.exit("no active vendor/customer link for those slugs")
            cred, token = await issue_sdk_credential(conn, settings.sdk_token_secret, ids["vendor"], ids["customer"], args.label)
            print(f"credential {cred}\n{token}")
        elif args.cmd == "list":
            for r in await conn.fetch(
                    """SELECT s.id, v.slug AS vendor, c.slug AS customer, s.label, s.created_at, s.revoked_at
                       FROM sdk_credentials s JOIN organizations v ON v.id = s.vendor_org_id
                       JOIN organizations c ON c.id = s.customer_org_id ORDER BY s.created_at"""):
                print(r["id"], r["vendor"], r["customer"], r["label"], "REVOKED" if r["revoked_at"] else "active")
        else:
            done = await conn.execute("UPDATE sdk_credentials SET revoked_at=now() WHERE id=$1 AND revoked_at IS NULL",
                                      UUID(args.credential_id))
            print("revoked" if done.endswith("1") else "not found or already revoked")
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("--vendor", required=True)
    issue.add_argument("--customer", required=True)
    issue.add_argument("--label", required=True)
    sub.add_parser("list")
    sub.add_parser("revoke").add_argument("credential_id")
    asyncio.run(main(ap.parse_args()))
