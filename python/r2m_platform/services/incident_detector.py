"""Production rule alerts. An intended policy DENY is enforcement working, not an incident."""
from uuid import UUID

from .evidence_builder import record_evidence


async def open_incident(conn, installation_id: UUID, category: str, severity: str, description: str, *,
                        execution_id: UUID | None = None, policy_decision_id: UUID | None = None) -> UUID:
    """Opens one incident per (installation, execution, category); returns the existing one otherwise."""
    existing = await conn.fetchval(
        """SELECT id FROM incidents WHERE installation_id=$1 AND category=$2 AND status <> 'resolved'
           AND execution_id IS NOT DISTINCT FROM $3""", installation_id, category, execution_id)
    if existing:
        return existing
    incident_id = await conn.fetchval(
        """INSERT INTO incidents(installation_id, execution_id, policy_decision_id, severity, category, description)
           VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
        installation_id, execution_id, policy_decision_id, severity, category, description)
    await record_evidence(conn, installation_id, "incident_opened",
                          {"incident_id": incident_id, "category": category, "severity": severity,
                           "description": description, "execution_id": execution_id},
                          execution_id=execution_id, incident_id=incident_id)
    return incident_id


async def detect_for_event(conn, installation_id: UUID, ev) -> None:
    if ev.kind == "execution.ended" and ev.status == "failed":
        await open_incident(conn, installation_id, "execution_failed", "medium",
                            f"Execution ended with status failed ({ev.name})", execution_id=ev.execution_id)
    elif ev.kind == "error" and ev.severity in ("error", "critical"):
        await open_incident(conn, installation_id, f"sdk_error:{ev.name}"[:100], "medium",
                            f"SDK reported a failure: {ev.name}", execution_id=ev.execution_id)
    elif ev.severity == "critical":
        await open_incident(conn, installation_id, "critical_event", "high",
                            f"Agent reported a critical event: {ev.name}", execution_id=ev.execution_id)
