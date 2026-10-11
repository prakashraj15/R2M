"""get_service_health: read-only, traced (coverage=observed)."""
from ..service_state import SERVICE_KEY

TOOL = "get_service_health"


def register(client, world):
    @client.tool(TOOL, risk="low", component=TOOL)
    def get_service_health(service_key: str = SERVICE_KEY) -> dict:
        svc = world.get_service(service_key)
        if svc is None:
            raise LookupError(f"unknown simulated service {service_key}")
        return dict(svc)

    return get_service_health
