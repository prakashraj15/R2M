"""Optional Keewano historical backfill (spec §7.4). Disabled unless explicitly invoked with --confirm.

    python scripts/seed_keewano.py --env-file .env --confirm

Follows the Keewano SpeedHacks guidance: a few hundred entities, two weeks of history, small typed
events only. Sends clearly synthetic past OpsPilot incidents through the same typed events and
entity model the live outbox uses. Keewano needs about five minutes to index them.

Story in the data (category / remediation / recommendation source: recovered of total):
  days 14-8, before Keewano: post-deploy errors mostly got restarts, and few recovered
  days 7-1, after Keewano:   history-informed rollbacks, and most recovered
Plus about 120 healthy observation runs. Deterministic: re-running re-sends the same entities.
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from keewano_check import load_env_file  # noqa: E402
from r2m_platform.services import keewano_adapter as k  # noqa: E402

# (category, remediation, source, recovered, total, (oldest_day, newest_day))
INCIDENTS = [
    ("post_deploy_errors", "restart", "deterministic", 6, 34, (8, 14)),
    ("post_deploy_errors", "rollback", "user", 9, 10, (8, 14)),
    ("post_deploy_errors", "scale", "deterministic", 2, 12, (8, 14)),
    ("post_deploy_errors", "rollback", "keewano", 44, 48, (1, 7)),
    ("post_deploy_errors", "restart", "deterministic", 2, 6, (1, 7)),
    ("capacity_pressure", "scale", "deterministic", 20, 26, (1, 14)),
    ("capacity_pressure", "restart", "deterministic", 5, 12, (1, 14)),
    ("capacity_pressure", "scale", "keewano", 22, 25, (1, 7)),
    ("capacity_pressure", "rollback", "user", 1, 5, (1, 14)),
]
HEALTHY_RUNS = 120
VERSIONS = ["v1.9", "v2.0", "v2.1"]


def streams(seed: int = 2026):
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    n = 0

    def ts(days: tuple[int, int]) -> int:
        return int((now - timedelta(days=rng.randint(*days), minutes=rng.randint(0, 1439))).timestamp())

    for category, remediation, source, recovered, total, days in INCIDENTS:
        outcomes = [True] * recovered + [False] * (total - recovered)
        rng.shuffle(outcomes)
        for ok in outcomes:
            n += 1
            start = ts(days)
            yield k.entity_id(f"history:{n}"), [
                k._ev(2000, rng.choice(VERSIONS), start),
                k._ev(2001, category, start),
                k._ev(2002, remediation, start + 30),
                k._ev(2004, "approval_required" if remediation == "rollback" else "allow", start + 31),
                k._ev(2006, rng.randint(80, 2400), start + 40),
                k._ev(2008, source, start + 300),
                k._ev(2003, ok, start + 300),
            ]
    for _ in range(HEALTHY_RUNS):
        n += 1
        start = ts((1, 14))
        yield k.entity_id(f"history:{n}"), [k._ev(2000, rng.choice(VERSIONS), start),
                                            k._ev(2006, rng.randint(40, 400), start + 5)]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true", help="actually send the synthetic history to Keewano")
    ap.add_argument("--env-file", help="load KEEWANO_* variables from this file (values are never printed)")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    items = list(streams())
    print(f"{len(items)} synthetic entities prepared (two weeks)")
    if not args.confirm:
        print("dry run: pass --confirm to send them (requires KEEWANO_API_KEY)")
        return 0
    async with k.ingest_client() as http:
        await k.register_event_types(http)
        for i, (install_id, events) in enumerate(items, 1):
            await k.post_stream(http, install_id, events)
            if i % 50 == 0:
                print(f"  sent {i}/{len(items)}")
    print("done. Keewano indexes in about 5 minutes; then: python scripts/keewano_check.py --env-file .env --query")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
