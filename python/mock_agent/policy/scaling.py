"""CAPACITY-001: scaling above 4 replicas requires approval; outside 1..12 is never allowed."""
from r2m import PolicyContext, PolicyResult, policy

APPROVAL_THRESHOLD = 4
HARD_MAX = 12


@policy(id="CAPACITY-001", version="1.0.0", owner="atlas-applied-ai",
        description="Scaling over 4 replicas requires approval; hard limit 12",
        tools=["scale_instances"], scope="production")
def CAPACITY_001(ctx: PolicyContext) -> PolicyResult:
    try:
        replicas = int(ctx.arguments["desired_replicas"])
    except (KeyError, TypeError, ValueError):
        return PolicyResult.deny("INVALID_REPLICA_COUNT")
    if replicas < 1:
        return PolicyResult.deny("REPLICAS_BELOW_MINIMUM")
    if replicas > HARD_MAX:
        return PolicyResult.deny("REPLICAS_ABOVE_HARD_LIMIT", f"max {HARD_MAX}")
    if replicas > APPROVAL_THRESHOLD:
        return PolicyResult.require_approval("SCALING_ABOVE_4_REQUIRES_APPROVAL")
    return PolicyResult.allow("WITHIN_CAPACITY_LIMIT")
