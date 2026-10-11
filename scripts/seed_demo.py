"""Idempotent synthetic demo data with deterministic UUIDv5 ids. All records are fake and labeled demo."""
import asyncio
import hashlib
import json
import pathlib
import sys
import uuid

import asyncpg

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))
from r2m_platform.config import load_settings  # noqa: E402
from r2m_platform.database import ssl_context  # noqa: E402
from r2m_platform.services.simulation import BASELINES, SERVICE_KEY, STATE_FIELDS  # noqa: E402

NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://r2m.demo/seed")


def uid(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"{kind}:{key}")


ORGS = [("atlas", "Atlas Applied AI", "vendor", "atlas-applied-ai"),
        ("meridian", "Meridian Financial", "customer", "meridian-financial"),
        ("northwind", "Northwind Health", "customer", "northwind-health")]  # unrelated tenant for isolation tests
USERS = [("dev@atlas.demo", "Avery (Vendor Developer)", "atlas", "vendor_developer"),
         ("release@atlas.demo", "Rowan (Vendor Release Manager)", "atlas", "vendor_release_manager"),
         ("security@meridian.demo", "Sam (Customer Security Reviewer)", "meridian", "customer_security"),
         ("ops@meridian.demo", "Morgan (Customer Operations Viewer)", "meridian", "customer_ops"),
         ("security@northwind.demo", "Nico (Northwind Security Reviewer)", "northwind", "customer_security")]
CUSTOMERS = ("meridian", "northwind")
SEED_BUILD = "1.0.0-seed"
TOOLS = ["get_service_health", "read_logs", "get_deployment_history", "restart_service", "scale_instances",
         "rollback_deployment"]
COMPONENTS = [("orchestrator", "orchestrator", "OpsPilot orchestrator"), ("sim-llm", "model", "Simulated LLM (no vendor)"),
              ("conversation-memory", "memory", "Conversation memory"), ("r2m-postgres", "storage", "R2M Postgres (Aiven)"),
              ("container", "compute", "R2M container"), ("policy-gateway", "gateway", "R2M SDK policy gateway"),
              *[(t, "tool", t) for t in TOOLS]]
EDGES = [("orchestrator", "sim-llm", "calls"), ("orchestrator", "conversation-memory", "reads"),
         ("conversation-memory", "r2m-postgres", "stores"), ("orchestrator", "container", "runs_on"),
         ("orchestrator", "policy-gateway", "calls"), *[("policy-gateway", t, "guards") for t in TOOLS]]


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


async def seed(conn) -> None:
    async with conn.transaction():
        for key, name, kind, slug in ORGS:
            await conn.execute("INSERT INTO organizations(id,name,kind,slug) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                               uid("org", key), name, kind, slug)
        for email, display, org, role in USERS:
            await conn.execute("INSERT INTO users(id,email,display_name,is_demo) VALUES ($1,$2,$3,true) ON CONFLICT DO NOTHING",
                               uid("user", email), email, display)
            await conn.execute("INSERT INTO org_memberships(id,organization_id,user_id,role) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                               uid("membership", f"{email}:{role}"), uid("org", org), uid("user", email), role)
        agent = uid("agent", "opspilot")
        await conn.execute(
            """INSERT INTO agents(id,vendor_org_id,slug,name,description,sdk_version) VALUES ($1,$2,'opspilot','OpsPilot',$3,'0.1.0')
               ON CONFLICT DO NOTHING""", agent, uid("org", "atlas"),
            "AI operations assistant for the synthetic payments-api service (demo).")
        build = uid("build", SEED_BUILD)
        await conn.execute(
            """INSERT INTO builds(id,agent_id,version,source_digest,artifact_digest) VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING""",
            build, agent, SEED_BUILD, digest("seed-source:opspilot"), digest("seed-artifact:opspilot"))
        for cust in CUSTOMERS:
            await conn.execute("INSERT INTO vendor_customer_links(id,vendor_org_id,customer_org_id) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
                               uid("link", f"atlas:{cust}"), uid("org", "atlas"), uid("org", cust))
            inst = uid("installation", f"opspilot:{cust}")
            await conn.execute(
                """INSERT INTO agent_installations(id,agent_id,customer_org_id,environment,status) VALUES ($1,$2,$3,'production','active')
                   ON CONFLICT DO NOTHING""", inst, agent, uid("org", cust))
            await conn.execute(
                """INSERT INTO deployments(id,installation_id,build_id,status,deployed_at) VALUES ($1,$2,$3,'deployed',now())
                   ON CONFLICT DO NOTHING""", uid("deployment", f"opspilot:{cust}:{SEED_BUILD}"), inst, build)
            for key, kind, label in COMPONENTS:
                await conn.execute(
                    """INSERT INTO agent_components(id,installation_id,component_key,kind,label,metadata) VALUES ($1,$2,$3,$4,$5,$6)
                       ON CONFLICT DO NOTHING""", uid("component", f"{cust}:{key}"), inst, key, kind, label,
                    json.dumps({"demo": True}))
            for src, dst, kind in EDGES:
                await conn.execute(
                    """INSERT INTO component_edges(id,installation_id,source_component_id,target_component_id,edge_kind)
                       VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING""", uid("edge", f"{cust}:{src}:{dst}"), inst,
                    uid("component", f"{cust}:{src}"), uid("component", f"{cust}:{dst}"), kind)
            base = BASELINES["degraded"]
            await conn.execute(
                f"""INSERT INTO simulation_services(id,customer_org_id,service_key,environment,{",".join(STATE_FIELDS)})
                    VALUES ($1,$2,$3,'production',$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT DO NOTHING""",
                uid("service", f"{cust}:{SERVICE_KEY}"), uid("org", cust), SERVICE_KEY, *(base[k] for k in STATE_FIELDS))
            await conn.execute(
                "INSERT INTO integration_configs(id,organization_id,provider,enabled) VALUES ($1,$2,'keewano',false) ON CONFLICT DO NOTHING",
                uid("integration", f"{cust}:keewano"), uid("org", cust))


async def main() -> None:
    settings = load_settings()
    conn = await asyncpg.connect(settings.database_url, ssl=ssl_context(settings))
    try:
        await seed(conn)
        print("seeded demo data (synthetic). identities:", ", ".join(u[0] for u in USERS))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
