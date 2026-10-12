"""Password sign-in, signed sessions, role permissions and tenant scope."""
import base64
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass, field
from uuid import UUID

from .database import Scope, apply_scope
from .errors import forbidden, not_found

SESSION_COOKIE = "r2m_session"

PERMISSIONS: dict[str, set[str]] = {
    "vendor_developer": {"policy.submit", "incident.manage", "integration.query", "demo.use"},
    "vendor_release_manager": {"release.evaluate", "release.deploy", "evidence.export", "demo.use"},
    "customer_security": {"approval.decide", "incident.manage", "evidence.export", "integration.query", "integration.configure", "demo.use"},
    "customer_ops": {"incident.manage", "demo.use"},
    "org_admin": {"integration.configure"},
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# scrypt (RFC 7914) at n=2^14, r=8, p=1: ~16 MiB and tens of ms per check, from the stdlib.
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    return f"scrypt${_b64(salt)}${_b64(hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT))}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. Unknown users verify against a throwaway hash so timing doesn't reveal accounts."""
    try:
        scheme, salt, key = (stored or _DUMMY_HASH).split("$")
        ok = scheme == "scrypt" and hmac.compare_digest(
            hashlib.scrypt(password.encode(), salt=_unb64(salt), **_SCRYPT), _unb64(key))
    except ValueError:
        return False
    return ok and stored is not None


def password_version(password_hash: str) -> str:
    """Short fingerprint of the stored hash. Sessions carry it, so setting a new password ends every older session."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def sign_session(key: str, user_id: UUID, ttl: int, pv: str) -> str:
    payload = _b64(json.dumps({"uid": str(user_id), "pv": pv, "exp": int(time.time()) + ttl}).encode())
    sig = _b64(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_session(key: str, token: str) -> tuple[UUID, str] | None:
    try:
        payload, sig = token.split(".", 1)
        expected = _b64(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_unb64(payload))
        return (UUID(data["uid"]), data["pv"]) if data["exp"] > time.time() else None
    except (ValueError, KeyError, TypeError):
        return None


@dataclass
class Actor:
    user_id: UUID
    email: str
    display_name: str
    memberships: list[dict] = field(default_factory=list)  # {organization_id, name, kind, slug, role}

    @property
    def org_ids(self) -> list[UUID]:
        return list({m["organization_id"] for m in self.memberships})

    def roles_in(self, org_id: UUID) -> set[str]:
        return {m["role"] for m in self.memberships if m["organization_id"] == org_id}

    def can(self, permission: str, org_id: UUID) -> bool:
        return any(permission in PERMISSIONS.get(r, ()) for r in self.roles_in(org_id))

    def require(self, permission: str, org_id: UUID) -> None:
        if not self.can(permission, org_id):
            raise forbidden(f"requires permission {permission} in the owning organization")


async def load_actor(conn, user_id: UUID, pv: str) -> tuple[Actor, Scope] | None:
    """One round trip: loads the actor and applies their row-level-security scope to this connection."""
    rows = await conn.fetch(
        """WITH s AS (SELECT * FROM r2m_apply_actor_scope($1))
           SELECT u.password_hash, u.id, u.email, u.display_name, m.organization_id, o.name, o.kind, o.slug, m.role,
                  s.installations AS scope_installations, s.orgs AS scope_orgs
           FROM s CROSS JOIN users u LEFT JOIN org_memberships m ON m.user_id = u.id
           LEFT JOIN organizations o ON o.id = m.organization_id
           WHERE u.id=$1 AND u.password_hash IS NOT NULL ORDER BY o.name, m.role""", user_id)
    if not rows:
        return None
    if password_version(rows[0]["password_hash"]) != pv:  # stale session: undo the scope the query just applied
        await apply_scope(conn, Scope((), ()))
        return None
    memberships = [{k: r[k] for k in ("organization_id", "name", "kind", "slug", "role")} for r in rows if r["role"]]
    actor = Actor(rows[0]["id"], rows[0]["email"], rows[0]["display_name"], memberships)
    return actor, Scope(tuple(rows[0]["scope_installations"]), tuple(rows[0]["scope_orgs"]))


_DUMMY_HASH = hash_password(os.urandom(16).hex())


# ---- per-customer SDK credentials ---------------------------------------------
# token = r2m_sdk_<credential id hex>_<HMAC-SHA256(SDK_TOKEN_SECRET, id hex)>. Derivable, so nothing secret is
# stored in the database; revocation and the vendor/customer scope live in sdk_credentials.
SDK_TOKEN = re.compile(r"^r2m_sdk_([0-9a-f]{32})_([0-9a-f]{64})$")


@dataclass(frozen=True)
class SdkPrincipal:
    credential_id: UUID
    vendor_org_id: UUID
    customer_org_id: UUID
    token: str


def sdk_token(secret: str, credential_id: UUID) -> str:
    return f"r2m_sdk_{credential_id.hex}_{hmac.new(secret.encode(), credential_id.hex.encode(), hashlib.sha256).hexdigest()}"


def parse_sdk_token(secret: str, token: str) -> UUID | None:
    m = SDK_TOKEN.match(token)
    if not m:
        return None
    credential_id = UUID(m.group(1))
    return credential_id if hmac.compare_digest(sdk_token(secret, credential_id), token) else None


async def load_sdk_principal(conn, credential_id: UUID, token: str) -> tuple[SdkPrincipal, Scope] | None:
    """One round trip: checks the credential is live and applies its row-level-security scope."""
    row = await conn.fetchrow("SELECT * FROM r2m_apply_sdk_scope($1)", credential_id)
    if not row:
        return None
    return (SdkPrincipal(credential_id, row["vendor_org_id"], row["customer_org_id"], token),
            Scope(tuple(row["installations"]), tuple(row["orgs"])))


async def issue_sdk_credential(conn, secret: str, vendor_org_id: UUID, customer_org_id: UUID, label: str,
                               reuse: bool = False) -> tuple[UUID, str]:
    """New credential for an actively linked vendor/customer pair (or the live one with this label if reuse)."""
    if reuse:  # concurrency-safe get-or-create on the live (pair, label) unique index
        credential_id = await conn.fetchval(
            """WITH ins AS (INSERT INTO sdk_credentials(vendor_org_id, customer_org_id, label) VALUES ($1,$2,$3)
                            ON CONFLICT (vendor_org_id, customer_org_id, label) WHERE revoked_at IS NULL DO NOTHING
                            RETURNING id)
               SELECT id FROM ins UNION ALL SELECT id FROM sdk_credentials WHERE vendor_org_id=$1
               AND customer_org_id=$2 AND label=$3 AND revoked_at IS NULL LIMIT 1""",
            vendor_org_id, customer_org_id, label)
    else:
        credential_id = await conn.fetchval(
            "INSERT INTO sdk_credentials(vendor_org_id, customer_org_id, label) VALUES ($1,$2,$3) RETURNING id",
            vendor_org_id, customer_org_id, label)
    return credential_id, sdk_token(secret, credential_id)


# Installations an actor may see: their customer org's, or their vendor's agents at actively linked customers.
SCOPE_SQL = """
SELECT i.id, i.agent_id, i.customer_org_id, i.environment, i.status, i.last_heartbeat_at, a.vendor_org_id
FROM agent_installations i JOIN agents a ON a.id = i.agent_id
WHERE (i.customer_org_id = ANY($1::uuid[])
   OR (a.vendor_org_id = ANY($1::uuid[]) AND EXISTS (
        SELECT 1 FROM vendor_customer_links l WHERE l.vendor_org_id = a.vendor_org_id
        AND l.customer_org_id = i.customer_org_id AND l.status = 'active')))
"""


async def scoped_installations(conn, actor: Actor, agent_id: UUID | None = None) -> list[dict]:
    sql = SCOPE_SQL + (" AND i.agent_id = $2" if agent_id else "") + " ORDER BY i.environment, i.id"
    args = (actor.org_ids, agent_id) if agent_id else (actor.org_ids,)
    return [dict(r) for r in await conn.fetch(sql, *args)]


async def agent_installations(conn, actor: Actor, agent_id: UUID, installation_id: UUID | None = None) -> list[dict]:
    """Accessible installations of an agent (optionally just one). 404 when none — never reveals existence."""
    rows = await scoped_installations(conn, actor, agent_id)
    if installation_id:
        rows = [r for r in rows if r["id"] == installation_id]
    if not rows:
        raise not_found("agent")
    return rows


async def installation_in_scope(conn, actor: Actor, installation_id: UUID) -> dict:
    row = await conn.fetchrow(SCOPE_SQL + " AND i.id = $2", actor.org_ids, installation_id)
    if not row:
        raise not_found("installation")
    return dict(row)
