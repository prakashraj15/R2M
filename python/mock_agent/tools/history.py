"""get_deployment_history: read-only, traced (coverage=observed)."""
from ..service_state import SERVICE_KEY

TOOL = "get_deployment_history"


def register(client, world):
    @client.tool(TOOL, risk="low", component=TOOL)
    def get_deployment_history(service_key: str = SERVICE_KEY) -> dict:
        svc = world.get_service(service_key) or {}
        actions = world.deployment_history(service_key)
        return {
            "service_key": service_key,
            "current_version": svc.get("deployment_version"),
            "previous_version": svc.get("previous_version"),
            "recent_actions": [{"kind": a.get("kind"), "authorized": a.get("authorized"),
                                "created_at": str(a.get("created_at"))} for a in actions[:10]],
        }

    return get_deployment_history
