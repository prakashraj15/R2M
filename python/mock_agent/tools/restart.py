"""restart_service: low risk, but still gated so the world gets a grant for the mutation."""
from .. import service_state
from ..service_state import SERVICE_KEY

TOOL = "restart_service"


def register(client, world):
    from . import apply

    @client.tool(TOOL, risk="low", guarded=True, component=TOOL)
    def restart_service(service_key: str = SERVICE_KEY) -> dict:
        svc = world.get_service(service_key)
        return apply(world, TOOL, service_state.restart_effect(svc), service_key)

    return restart_service
