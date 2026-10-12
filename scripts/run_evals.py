"""Deterministic pre-deployment evaluation run for an OpsPilot build (spec §6, §10 step 5).

    python scripts/run_evals.py --agent opspilot --build safe-1.0
    python scripts/run_evals.py --agent opspilot --build faulty-1.0      # must fail -> release blocked

Runs every suite offline in the sandbox (no production traffic, no shared DB), prints the results,
then posts each suite to POST /api/v1/agents/{agentId}/evaluations with the SDK bearer token.
Exit code 0 = all mandatory cases passed, 1 = at least one mandatory failure, 2 = upload error.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))

import httpx  # noqa: E402

from mock_agent.build import AGENT_SLUG, build  # noqa: E402
from mock_agent.evals import mandatory_failures, run_all  # noqa: E402

SEED_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://r2m.demo/seed")


def agent_id(slug: str) -> str:
    return str(uuid.uuid5(SEED_NS, f"agent:{slug}"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", default=AGENT_SLUG, choices=[AGENT_SLUG])
    ap.add_argument("--build", default=os.environ.get("OPSPILOT_BUILD_VERSION"),
                    help="safe-<n> | faulty-<n>; defaults to OPSPILOT_BUILD_VERSION (the opspilot container's version)")
    ap.add_argument("--api-url", default=os.environ.get("R2M_INTERNAL_API_URL") or os.environ.get("R2M_API_URL")
                    or "http://127.0.0.1:8000")
    ap.add_argument("--agent-id", default=None, help="defaults to the seeded deterministic id")
    ap.add_argument("--dry-run", action="store_true", help="run offline only; do not post results")
    ap.add_argument("--json", action="store_true", help="print the full result payloads")
    args = ap.parse_args()
    if not args.build:
        ap.error("--build is required (or set OPSPILOT_BUILD_VERSION)")

    b = build(args.build)
    print(f"OpsPilot build {b.version} ({b.variant})\n  source   {b.source_digest}\n  artifact {b.artifact_digest}")
    runs = run_all(b.version)
    for run in runs:
        passed = sum(c["status"] == "passed" for c in run["cases"])
        print(f"\n[{run['suite_key']}] {passed}/{len(run['cases'])} passed")
        for c in run["cases"]:
            mark = {"passed": "PASS", "failed": "FAIL", "error": "ERR ", "skipped": "SKIP"}[c["status"]]
            print(f"  {mark} {c['case_key']}{'' if c['mandatory'] else ' (optional)'}")
            if c["status"] != "passed":
                print(f"       expected {json.dumps(c['expected'], default=str)}")
                shown = {k: v for k, v in c["actual"].items() if k in c["expected"] or k.startswith("error")}
                print(f"       actual   {json.dumps(shown, default=str)}")
    if args.json:
        print(json.dumps(runs, indent=2, default=str))

    failures = mandatory_failures(runs)
    print(f"\nGate input: {'FAILED, release will be blocked' if failures else 'all mandatory cases passed'}"
          + (f" ({len(failures)} mandatory failures)" if failures else ""))

    if not args.dry_run:
        token = os.environ.get("SDK_INGEST_TOKEN") or os.environ.get("OPSPILOT_SDK_TOKEN")
        if not token:
            print("SDK_INGEST_TOKEN (or OPSPILOT_SDK_TOKEN) is not set; use --dry-run to skip uploading", file=sys.stderr)
            return 2
        aid = args.agent_id or agent_id(args.agent)
        with httpx.Client(base_url=args.api_url.rstrip("/") + "/api/v1", timeout=60,
                          headers={"Authorization": f"Bearer {token}"}) as http:
            for run in runs:
                resp = http.post(f"/agents/{aid}/evaluations", json=run)
                if resp.status_code >= 400:
                    print(f"upload {run['suite_key']} failed: {resp.status_code} {resp.text[:300]}", file=sys.stderr)
                    return 2
                body = resp.json()
                print(f"uploaded {run['suite_key']}: run {body['run_id']} -> {body['status']}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
