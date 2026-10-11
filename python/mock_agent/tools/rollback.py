"""rollback_deployment: high risk, guarded by DEPLOY-001.

``guarded=False`` exists only to build the faulty variant for fault-injection evals: the same
tool without its R2M gate, as if a developer dropped the decorator's policy binding.
"""
from .. import service_state
from ..policy import DEPLOY_001
from ..service_state import SERVICE_KEY

TOOL = "rollback_deployment"


def register(client, world, *, guarded: bool = True):
    from . import apply

    if guarded:
        decorate = client.tool(TOOL, risk="high", policies=[DEPLOY_001], component=TOOL)
    else:
        decorate = client.tool(TOOL, risk="high", guarded=False, component=TOOL)

    @decorate
    def rollback_deployment(target_version: str, service_key: str = SERVICE_KEY) -> dict:
        svc = world.get_service(service_key)
        return apply(world, TOOL, service_state.rollback_effect(svc, target_version), service_key)

    return rollback_deployment
