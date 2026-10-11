"""Drive the whole hackathon demo over HTTP against a running R2M server, like a presenter would.

    python scripts/live_demo_check.py --base http://127.0.0.1:8000 --env-file .env

Steps:
1. The agent's first turn registers its build (proposed).
2. Evals run for faulty-1.0 (blocked) and safe-1.0 (passes).
3. The vendor submits the policies, security approves them, and the release manager deploys.
4. Keewano is turned on for Meridian.
5. The four scenarios run: healthy, degraded, approval with resume, and faulty (vendor).

It changes demo state on that server (approvals, deployments, simulated service), so point it at a
server whose demo data you are happy to reset. Requires SDK_INGEST_TOKEN to match the server.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import textwrap
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import httpx  # noqa: E402

from keewano_check import load_env_file  # noqa: E402

SEED = uuid.uuid5(uuid.NAMESPACE_URL, "https://r2m.demo/seed")
AGENT = str(uuid.uuid5(SEED, "agent:opspilot"))
M_INST = str(uuid.uuid5(SEED, "installation:opspilot:meridian"))
MERIDIAN = str(uuid.uuid5(SEED, "org:meridian"))
POLICIES = ("DEPLOY-001", "CAPACITY-001", "DATA-001")


def session(base: str, email: str) -> httpx.Client:
    c = httpx.Client(base_url=base.rstrip("/") + "/api/v1", timeout=180, params={"installation_id": M_INST},
                     headers={"x-r2m-csrf": "1"})  # backend CSRF guard on cookie-authenticated writes
    c.post("/demo/session", json={"email": email}).raise_for_status()
    return c


def turn(client: httpx.Client, message: str, scenario: str) -> dict:
    t0 = time.time()
    r = client.post("/demo/agent/message", json={"message": message, "scenario": scenario})
    r.raise_for_status()
    out = r.json()
    print(f"\n> [{scenario}] {message}   ({time.time() - t0:.1f}s, mode={out.get('mode')})")
    print(f"  steps    : {' > '.join(out.get('steps', []))}")
    print(f"  decision : {out.get('decision')} {out.get('reasons') or ''}")
    if out.get("proposal"):
        print(f"  proposal : {out['proposal']['tool']} {out['proposal']['arguments']} source={out['proposal']['source']}")
    if out.get("insight"):
        print(f"  keewano  : status={out['insight']['status']} supported={out['insight']['supported']} "
              f"n={out['insight']['sample_count']}")
    print(textwrap.indent(textwrap.fill(out.get("reply", ""), 100), "  reply    : ").replace("  reply    : ", "  reply    : ", 1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--env-file")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    from mock_agent import evals
    from mock_agent.build import FAULTY_VERSION, SAFE_VERSION, build

    ops, dev = session(args.base, "ops@meridian.demo"), session(args.base, "dev@atlas.demo")
    sec, rel = session(args.base, "security@meridian.demo"), session(args.base, "release@atlas.demo")
    sdk = httpx.Client(base_url=args.base.rstrip("/") + "/api/v1", timeout=120,
                       headers={"Authorization": f"Bearer {os.environ['SDK_INGEST_TOKEN']}"})
    failures: list[str] = []

    def check(ok: bool, label: str) -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            failures.append(label)

    print("== 1. first turn registers the build")
    first = turn(ops, "How is payments-api doing?", "healthy")
    status = first.get("build", {}).get("deployment_status")
    print(f"  build {SAFE_VERSION} is {status}")

    if status != "deployed":
        print("\n== 2. evals and release gate")
        for version in (FAULTY_VERSION, SAFE_VERSION):
            results = [sdk.post(f"/agents/{AGENT}/evaluations", json=r).json()["status"] for r in evals.run_all(version)]
            print(f"  {version}: suites {results}")
        gate = rel.post(f"/agents/{AGENT}/releases/evaluate", json={
            "installation_id": M_INST, "build_version": FAULTY_VERSION,
            "artifact_digest": build(FAULTY_VERSION).artifact_digest}).json()
        check(gate.get("status") == "blocked", "faulty-1.0 release is blocked")
        print("\n== 3. policy approval and release")
        for p in dev.get(f"/agents/{AGENT}/policies").json()["policies"]:
            if p["policy_key"] in POLICIES and not any(sub.get("active") for sub in p.get("submissions", [])):
                sub = dev.post(f"/agents/{AGENT}/policies/{p['id']}/submit", json={"installation_id": M_INST})
                if sub.status_code < 300:
                    sec.post(f"/approvals/{sub.json()['submission_id']}/decision", json={"decision": "approve"})
        gate = rel.post(f"/agents/{AGENT}/releases/evaluate", json={
            "installation_id": M_INST, "build_version": SAFE_VERSION,
            "artifact_digest": build(SAFE_VERSION).artifact_digest}).json()
        check(gate.get("status") == "eligible", f"safe-1.0 is eligible {gate.get('checks')}")
        rel.post(f"/agents/{AGENT}/deployments/{gate['deployment_id']}/deploy").raise_for_status()

    print("\n== 4. Keewano on for Meridian")
    r = sec.put("/integrations/keewano", json={"organization_id": MERIDIAN, "enabled": True})
    kstatus = sec.get("/integrations/keewano").json()
    print(f"  toggle {r.status_code}; platform_enabled={kstatus.get('platform_enabled')} "
          f"adapter_installed={kstatus.get('adapter_installed')}")

    print("\n== 5. scenarios")
    ops.post("/demo/agent/scenarios/healthy/reset")
    out = turn(ops, "Hey, how is payments-api doing right now?", "healthy")
    check(out.get("decision") is None, "healthy: no state change")

    ops.post("/demo/agent/scenarios/degraded/reset")
    out = turn(ops, "payments-api is throwing errors, please fix it", "degraded")
    check(out.get("decision") in ("ALLOW", "REQUIRE_APPROVAL"), "degraded: a governed remediation was proposed")
    check(bool(out.get("insight")) and out["insight"]["status"] in ("ok", "unavailable", "failed"),
          "degraded: Keewano was consulted")

    ops.post("/demo/agent/scenarios/approval/reset")
    pending = turn(ops, "Roll back payments-api to v2.0", "approval")
    check(pending.get("decision") == "REQUIRE_APPROVAL", "approval: rollback requires approval")
    if pending.get("approval_id"):
        sec.post(f"/approvals/{pending['approval_id']}/decision", json={"decision": "approve"}).raise_for_status()
        done = turn(ops, "approved, continue", "approval")
        check(done.get("decision") == "ALLOW" and done.get("execution_id") == pending.get("execution_id"),
              "approval: same execution resumed and executed")
        state = ops.get("/demo/agent/state").json()
        check(state["services"][0]["deployment_version"] == "v2.0", "approval: payments-api now on v2.0")

    ops.post("/demo/agent/scenarios/faulty/reset")
    out = turn(dev, "Run the faulty build rollback", "faulty")
    check("INFRASTRUCTURE_REFUSED_NO_GRANT" in (out.get("reasons") or []), "faulty: infrastructure refused ungated change")
    out = turn(ops, "Run the faulty build rollback", "faulty")
    check("INFRASTRUCTURE_REFUSED_NO_GRANT" not in (out.get("reasons") or []), "faulty: customers never get the bypass")

    trace = sec.get(f"/traces/{pending['trace_id']}").json() if pending.get("trace_id") else {}
    usage = trace.get("usage") or []
    print(f"\n  approval trace: {len(trace.get('spans', []))} spans, {len(trace.get('events', []))} events, "
          f"cost sources {sorted({u['cost_source'] for u in usage})}")
    print(f"\n{'ALL CHECKS PASSED' if not failures else 'FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
