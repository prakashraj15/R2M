"""Evidence records with SHA-256 over canonical JSON, plus append-only audit events.

Checksums detect tampering of stored bodies; they are not independent timestamp attestation.
"""
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

CAVEAT = ("SHA-256 checksums detect modification of stored evidence bodies. They are not WORM storage, "
          "third-party timestamping or a compliance attestation.")


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(obj) -> str:
    data = obj if isinstance(obj, (bytes, str)) else canonical_json(obj)
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


async def record_evidence(conn, installation_id: UUID, evidence_type: str, body: dict, *, execution_id=None,
                          evaluation_case_id=None, policy_revision_id=None, incident_id=None) -> UUID:
    stored = json.loads(canonical_json(body))  # store exactly what was hashed
    return await conn.fetchval(
        """INSERT INTO evidence_items(installation_id, execution_id, evaluation_case_id, policy_revision_id,
           incident_id, evidence_type, body, sha256) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
        installation_id, execution_id, evaluation_case_id, policy_revision_id, incident_id,
        evidence_type, stored, sha256_hex(stored))


async def audit(conn, actor_user_id, organization_id, action: str, target_type: str, target_id=None,
                request_id: str | None = None, details: dict | None = None) -> None:
    await conn.execute(
        """INSERT INTO audit_events(actor_user_id, organization_id, action, target_type, target_id, request_id, details)
           VALUES ($1,$2,$3,$4,$5,$6,$7)""",
        actor_user_id, organization_id, action, target_type, target_id, request_id,
        json.loads(canonical_json(details or {})))


async def list_evidence(conn, installation_ids: list[UUID], limit: int = 200) -> list[dict]:
    rows = await conn.fetch(
        """SELECT id, installation_id, execution_id, evaluation_case_id, policy_revision_id, incident_id,
                  evidence_type, body, sha256, created_at
           FROM evidence_items WHERE installation_id = ANY($1::uuid[]) ORDER BY created_at DESC LIMIT $2""",
        installation_ids, limit)
    return [{**dict(r), "integrity_ok": sha256_hex(r["body"]) == r["sha256"]} for r in rows]


async def export_bundle(conn, installation_ids: list[UUID]) -> dict:
    items = await list_evidence(conn, installation_ids, limit=10000)
    manifest = [{"id": str(i["id"]), "sha256": i["sha256"]} for i in items]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "manifest_sha256": sha256_hex(manifest),
        "caveat": CAVEAT,
    }
