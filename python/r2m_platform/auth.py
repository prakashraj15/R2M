"""Signed demo sessions, role permissions and tenant scope. DEMO AUTH — NOT PRODUCTION AUTH."""
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from uuid import UUID

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


def sign_session(key: str, user_id: UUID, ttl: int) -> str:
    payload = _b64(json.dumps({"uid": str(user_id), "exp": int(time.time()) + ttl}).encode())
    sig = _b64(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_session(key: str, token: str) -> UUID | None:
    try:
        payload, sig = token.split(".", 1)
        expected = _b64(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_unb64(payload))
        return UUID(data["uid"]) if data["exp"] > time.time() else None
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


async def load_actor(conn, user_id: UUID) -> Actor | None:
    rows = await conn.fetch(  # one round trip: the DB may be far away
        """SELECT u.id, u.email, u.display_name, m.organization_id, o.name, o.kind, o.slug, m.role
           FROM users u LEFT JOIN org_memberships m ON m.user_id = u.id LEFT JOIN organizations o ON o.id = m.organization_id
           WHERE u.id=$1 AND u.is_demo ORDER BY o.name, m.role""", user_id)
    if not rows:
        return None
    memberships = [{k: r[k] for k in ("organization_id", "name", "kind", "slug", "role")} for r in rows if r["role"]]
    return Actor(rows[0]["id"], rows[0]["email"], rows[0]["display_name"], memberships)


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
