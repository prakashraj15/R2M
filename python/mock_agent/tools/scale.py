"""scale_instances: guarded by CAPACITY-001."""
from .. import service_state
from ..policy import CAPACITY_001
from ..service_state import SERVICE_KEY

TOOL = "scale_instances"


def register(client, world):
    from . import apply

    @client.tool(TOOL, risk="high", policies=[CAPACITY_001], component=TOOL)
    def scale_instances(desired_replicas: int, service_key: str = SERVICE_KEY) -> dict:
        svc = world.get_service(service_key)
        return apply(world, TOOL, service_state.scale_effect(svc, int(desired_replicas)), service_key)

    return scale_instances
