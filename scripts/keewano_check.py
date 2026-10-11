"""Check Keewano credentials and the live MCP server. Never prints secret values.

    python scripts/keewano_check.py --env-file .env            # PAT: MCP handshake + tools/list
    python scripts/keewano_check.py --env-file .env --ingest   # API key: register event types (idempotent)
    python scripts/keewano_check.py --env-file .env --query    # run the history + before/after queries
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))


def load_env_file(path: str) -> None:
    """Minimal KEY=VALUE loader (no shell expansion). Existing environment variables win."""
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def describe(name: str) -> str:
    v = os.environ.get(name, "")
    if not v:
        return "missing"
    return f"set ({len(v)} chars, prefix '{v[:6]}...')" if len(v) > 12 else f"set but only {len(v)} chars: looks wrong"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--query", action="store_true")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    from r2m_platform.services import keewano_adapter as k

    print(f"KEEWANO_PAT     {describe('KEEWANO_PAT')}   (Settings > Personal > Security; used for MCP)")
    print(f"KEEWANO_API_KEY {describe('KEEWANO_API_KEY')}   (Settings > Project > API Keys; used for ingestion)")
    print(f"OPENAI_API_KEY  {describe('OPENAI_API_KEY')}")

    rc = 0
    try:
        async with k.McpSession(os.environ.get("KEEWANO_MCP_URL") or "https://api.keewano.com/mcp",
                                os.environ["KEEWANO_PAT"]) as mcp:
            tools = (await mcp.rpc("tools/list", {})).get("tools") or []
        print(f"\nMCP OK: {len(tools)} tools")
        for t in tools:
            props = ", ".join((t.get("inputSchema") or {}).get("properties", {}).keys())
            print(f"  - {t.get('name')}({props}): {(t.get('description') or '').strip()[:90]}")
        tool, arg, extra = k.pick_sql_tool(tools, k.project_id_hint())
        print(f"SQL tool chosen: {tool} (query argument '{arg}'{', extra ' + str(list(extra)) if extra else ''})")
    except Exception as exc:
        print(f"\nMCP check failed: {type(exc).__name__}: {exc}")
        rc = 1

    if args.ingest:
        try:
            async with k.ingest_client() as http:
                await k.register_event_types(http)
            print(f"Ingestion OK: {len(k.EVENT_TYPES)} custom event types registered (hash {k.CUSTOM_EVENTS_HASH})")
        except Exception as exc:
            print(f"Ingestion check failed: {type(exc).__name__}: {exc}")
            rc = 1

    if args.query and rc == 0:
        for category in ("post_deploy_errors", "capacity_pressure"):
            result = await k.query(f"category {category}", {})
            print(f"\nHistory for {category}: n={result['sample_count']}: {result['summary']}")
        tool, rows = await k.run_sql(k.before_after_sql())
        print("\nBefore/after (recovery by recommendation source):")
        print(json.dumps(rows, indent=2, default=str))
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
