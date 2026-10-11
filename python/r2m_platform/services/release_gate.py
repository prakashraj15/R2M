"""Build evaluation ingestion and the release gate.

eligible = build_evals_passed AND required_policies_approved AND artifact_hash_matches AND tenant_access_valid
"""
from uuid import UUID

from ..errors import ApiError, not_found
from .evidence_builder import audit, record_evidence, sha256_hex


async def ingest_run(conn, agent_id: UUID, body) -> dict:
    """Store one suite run from scripts/run_evals.py (pre-deployment CI only, never production traffic)."""
    failed = any(c.mandatory and c.status in ("failed", "error") for c in body.cases)
    status = "failed" if failed else "passed"
    async with conn.transaction():
        await conn.execute(
            """INSERT INTO builds(agent_id, version, source_digest, artifact_digest) VALUES ($1,$2,$3,$4)
               ON CONFLICT (agent_id, artifact_digest) DO NOTHING""",
            agent_id, body.build.version, body.build.source_digest, body.build.artifact_digest)
        build = await conn.fetchrow("SELECT id, version FROM builds WHERE agent_id=$1 AND artifact_digest=$2",
                                    agent_id, body.build.artifact_digest)
        if build["version"] != body.build.version:
            raise ApiError(409, "conflict", "artifact digest already registered under another version")
        suite_id = await conn.fetchval(
            """INSERT INTO evaluation_suites(suite_key, description, mandatory) VALUES ($1,$2,$3)
               ON CONFLICT (suite_key) DO UPDATE SET description=EXCLUDED.description, mandatory=EXCLUDED.mandatory
               RETURNING id""", body.suite_key, body.suite_description, body.mandatory)
        summary = {"total": len(body.cases), "passed": sum(c.status == "passed" for c in body.cases),
                   "failed": sum(c.status in ("failed", "error") for c in body.cases),
                   "mandatory_failures": [c.case_key for c in body.cases if c.mandatory and c.status in ("failed", "error")]}
        run_id = await conn.fetchval(
            """INSERT INTO evaluation_runs(build_id, suite_id, status, started_at, finished_at, summary)
               VALUES ($1,$2,$3,coalesce($4, now()),coalesce($5, now()),$6) RETURNING id""",
            build["id"], suite_id, status, body.started_at, body.finished_at, summary)
        case_hashes = []
        for c in body.cases:
            digest = sha256_hex({"case_key": c.case_key, "status": c.status, "expected": c.expected, "actual": c.actual})
            case_hashes.append({"case_key": c.case_key, "sha256": digest})
            await conn.execute(
                """INSERT INTO evaluation_cases(run_id, case_key, mandatory, status, expected, actual, trace_id, evidence_hash)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                run_id, c.case_key, c.mandatory, c.status, c.expected, c.actual, c.trace_id, digest)
        evidence = {"run_id": run_id, "build_version": build["version"], "artifact_digest": body.build.artifact_digest,
                    "source_digest": body.build.source_digest, "suite_key": body.suite_key, "status": status,
                    "summary": summary, "cases": case_hashes}
        for inst in await conn.fetch("SELECT id FROM agent_installations WHERE agent_id=$1", agent_id):
            await record_evidence(conn, inst["id"], "evaluation_run", evidence)
    return {"run_id": run_id, "build_id": build["id"], "status": status, "summary": summary}


async def compute_gate(conn, installation: dict, build: dict, artifact_digest: str) -> dict:
    runs = await conn.fetch(
        """SELECT DISTINCT ON (s.id) s.suite_key, s.mandatory, er.status, er.summary
           FROM evaluation_runs er JOIN evaluation_suites s ON s.id = er.suite_id
           WHERE er.build_id=$1 ORDER BY s.id, er.started_at DESC""", build["id"])
    required_suites = {r["suite_key"] for r in await conn.fetch(
        """SELECT DISTINCT s.suite_key FROM evaluation_runs er JOIN evaluation_suites s ON s.id = er.suite_id
           JOIN builds b ON b.id = er.build_id WHERE b.agent_id=$1 AND s.mandatory""", installation["agent_id"])}
    latest = {r["suite_key"]: r for r in runs}
    missing = sorted(required_suites - set(latest))
    failing = sorted(k for k, r in latest.items() if r["mandatory"] and r["status"] != "passed")
    build_evals_passed = bool(runs) and not missing and not failing

    newest = await conn.fetch(
        """SELECT DISTINCT ON (policy_key) id, policy_key, version, artifact_hash FROM policy_revisions
           WHERE agent_id=$1 ORDER BY policy_key, created_at DESC""", installation["agent_id"])
    active = {r["revision_id"] for r in await conn.fetch(
        "SELECT revision_id FROM policy_activations WHERE installation_id=$1 AND active", installation["id"])}
    unapproved = [f"{p['policy_key']}@{p['version']}" for p in newest if p["id"] not in active]

    tenant_ok = await conn.fetchval(
        """SELECT EXISTS(SELECT 1 FROM vendor_customer_links WHERE vendor_org_id=$1 AND customer_org_id=$2 AND status='active')""",
        installation["vendor_org_id"], installation["customer_org_id"])
    checks = {
        "build_evals_passed": build_evals_passed,
        "required_policies_approved": not unapproved,
        "artifact_hash_matches": build["artifact_digest"] == artifact_digest,
        "tenant_access_valid": tenant_ok,
    }
    return {"eligible": all(checks.values()), "checks": checks,
            "details": {"missing_suites": missing, "failing_suites": failing, "unapproved_policies": unapproved,
                        "suites": [{"suite_key": k, "status": r["status"], "summary": r["summary"]} for k, r in latest.items()]}}


async def evaluate(conn, actor, installation: dict, build_version: str, artifact_digest: str, request_id) -> dict:
    actor.require("release.evaluate", installation["vendor_org_id"])
    build = await conn.fetchrow(
        "SELECT * FROM builds WHERE agent_id=$1 AND version=$2 ORDER BY created_at DESC LIMIT 1",
        installation["agent_id"], build_version)
    if not build:
        raise not_found("build")
    gate = await compute_gate(conn, installation, dict(build), artifact_digest)
    status = "eligible" if gate["eligible"] else "blocked"
    async with conn.transaction():
        dep_id = await conn.fetchval(
            """UPDATE deployments SET status=$3 WHERE installation_id=$1 AND build_id=$2
               AND status IN ('proposed','blocked','eligible') RETURNING id""", installation["id"], build["id"], status)
        if not dep_id:
            dep_id = await conn.fetchval(
                "INSERT INTO deployments(installation_id, build_id, status) VALUES ($1,$2,$3) RETURNING id",
                installation["id"], build["id"], status)
        body = {"deployment_id": dep_id, "build_version": build_version, "artifact_digest": artifact_digest, **gate}
        await record_evidence(conn, installation["id"], "release_gate", body)
        await audit(conn, actor.user_id, installation["vendor_org_id"], "release.evaluate", "deployment", dep_id, request_id, body)
    return {"deployment_id": dep_id, "status": status, **gate}


async def deploy(conn, actor, installation: dict, deployment_id: UUID, request_id) -> dict:
    actor.require("release.deploy", installation["vendor_org_id"])
    async with conn.transaction():
        dep = await conn.fetchrow(
            """SELECT d.*, b.artifact_digest, b.version, b.agent_id FROM deployments d JOIN builds b ON b.id = d.build_id
               WHERE d.id=$1 AND d.installation_id=$2 FOR UPDATE OF d""", deployment_id, installation["id"])
        if not dep:
            raise not_found("deployment")
        gate = await compute_gate(conn, installation, {"id": dep["build_id"], "artifact_digest": dep["artifact_digest"]},
                                  dep["artifact_digest"])
        if dep["status"] != "eligible" or not gate["eligible"]:
            raise ApiError(409, "release_blocked", "deployment is not eligible: " + ", ".join(
                k for k, ok in gate["checks"].items() if not ok) if not gate["eligible"] else "evaluate the release first")
        await conn.execute("UPDATE deployments SET status='retired' WHERE installation_id=$1 AND status='deployed'", installation["id"])
        await conn.execute("UPDATE deployments SET status='deployed', deployed_at=now() WHERE id=$1", deployment_id)
        body = {"deployment_id": deployment_id, "build_version": dep["version"], "artifact_digest": dep["artifact_digest"], **gate}
        await record_evidence(conn, installation["id"], "deployment_promoted", body)
        await audit(conn, actor.user_id, installation["vendor_org_id"], "release.deploy", "deployment", deployment_id, request_id, body)
    return {"deployment_id": deployment_id, "status": "deployed"}
