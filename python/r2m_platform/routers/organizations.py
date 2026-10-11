from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends

from ..auth import Actor, scoped_installations
from ..dependencies import actor, db
from ..errors import not_found
from ..services import metrics_rollup, registry

router = APIRouter(tags=["organizations"])


@router.get("/organizations")
async def organizations(a: Actor = Depends(actor), conn=Depends(db)):
    rows = await conn.fetch("SELECT id, name, kind, slug FROM organizations WHERE id = ANY($1::uuid[]) ORDER BY name", a.org_ids)
    return {"organizations": [{**dict(r), "roles": sorted(a.roles_in(r["id"]))} for r in rows]}


@router.get("/organizations/{org_id}/overview")
async def overview(org_id: UUID, range: Literal["1h", "24h", "7d", "30d"] = "24h", a: Actor = Depends(actor), conn=Depends(db)):
    if org_id not in a.org_ids:
        raise not_found("organization")
    installs = [i for i in await scoped_installations(conn, a) if org_id in (i["customer_org_id"], i["vendor_org_id"])]
    ids = [i["id"] for i in installs]
    integrations = await conn.fetch(
        "SELECT provider, enabled, last_success_at FROM integration_configs WHERE organization_id=$1", org_id)
    return {"organization_id": org_id, "range": range,
            "metrics": await metrics_rollup.summary(conn, ids, metrics_rollup.since(range)),
            "agents": await registry.list_agents(conn, installs),
            "integrations": [dict(r) for r in integrations]}
