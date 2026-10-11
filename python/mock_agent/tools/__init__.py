"""OpsPilot tools, bound per request to an R2M client and the synthetic world.

Read tools are traced (coverage=observed). Mutating tools are guarded: they pass the SDK policy
gate and get a single-use grant, and only then call ``world.apply_action``, which independently
refuses any mutation without that grant.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Protocol

from r2m import current_execution

from . import health, history, logs, restart, rollback, scale

if TYPE_CHECKING:
    from r2m import R2MClient


class World(Protocol):
    def get_service(self, service_key: str = ...) -> dict[str, Any] | None: ...
    def deployment_history(self, service_key: str = ...) -> list[dict[str, Any]]: ...
    def apply_action(self, tool: str, changes: dict[str, Any], execution_id: str | None,
                     service_key: str = ...) -> dict[str, Any]: ...


class InfrastructureRefused(RuntimeError):
    """The simulated infrastructure refused a mutation (no valid grant). Never retried."""

    def __init__(self, tool: str, result: dict[str, Any]):
        super().__init__(f"{tool} refused by simulated infrastructure: {result.get('reason')}")
        self.tool = tool
        self.result = result


def apply(world: World, tool: str, changes: dict[str, Any], service_key: str) -> dict[str, Any]:
    execution = current_execution()
    result = world.apply_action(tool, changes, execution.execution_id if execution else None, service_key)
    if not result.get("applied"):
        raise InfrastructureRefused(tool, result)
    return result


@dataclass(frozen=True)
class Toolbox:
    get_service_health: Callable[..., dict[str, Any]]
    read_logs: Callable[..., dict[str, Any]]
    get_deployment_history: Callable[..., dict[str, Any]]
    restart_service: Callable[..., dict[str, Any]]
    scale_instances: Callable[..., dict[str, Any]]
    rollback_deployment: Callable[..., dict[str, Any]]

    def by_name(self, name: str) -> Callable[..., dict[str, Any]]:
        return getattr(self, name)


def make_tools(client: "R2MClient", world: World, *, fault_injection: bool = False) -> Toolbox:
    """``fault_injection`` builds the *faulty* variant: rollback loses its R2M gate (eval/fault demo only)."""
    return Toolbox(
        get_service_health=health.register(client, world),
        read_logs=logs.register(client, world),
        get_deployment_history=history.register(client, world),
        restart_service=restart.register(client, world),
        scale_instances=scale.register(client, world),
        rollback_deployment=rollback.register(client, world, guarded=not fault_injection),
    )
