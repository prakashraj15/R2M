from uuid import UUID

from fastapi import APIRouter, Depends

from ..auth import Actor, agent_installations
from ..dependencies import actor, db, sdk
from ..errors import not_found
from ..schemas import EvalRunIn
from ..services import release_gate

router = APIRouter(tags=["evaluations"])


@router.get("/agents/{agent_id}/evaluations")
async def evaluations(agent_id: UUID, a: Actor = Depends(actor), conn=Depends(db)):
    await agent_installations(conn, a, agent_id)
    runs = await conn.fetch(
        """SELECT er.id, er.status, er.started_at, er.finished_at, er.summary, s.suite_key, s.mandatory,
                  b.id AS build_id, b.version, b.source_digest, b.artifact_digest
           FROM evaluation_runs er JOIN evaluation_suites s ON s.id = er.suite_id JOIN builds b ON b.id = er.build_id
           WHERE b.agent_id=$1 ORDER BY er.started_at DESC LIMIT 200""", agent_id)
    cases = await conn.fetch(
        """SELECT id, run_id, case_key, mandatory, status, expected, actual, trace_id, evidence_hash FROM evaluation_cases
           WHERE run_id = ANY($1::uuid[]) ORDER BY case_key""", [r["id"] for r in runs])
    return {"runs": [{**dict(r), "mandatory_failure": bool(r["summary"].get("mandatory_failures")),
                      "cases": [dict(c) for c in cases if c["run_id"] == r["id"]]} for r in runs]}


@router.post("/agents/{agent_id}/evaluations", status_code=201, dependencies=[Depends(sdk)])
async def ingest_evaluation(agent_id: UUID, body: EvalRunIn, conn=Depends(db)):
    if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM agents WHERE id=$1)", agent_id):
        raise not_found("agent")
    return await release_gate.ingest_run(conn, agent_id, body)
