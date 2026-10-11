from r2m import PolicyContext, PolicyResult, policy


@policy(id="TEST-ROLLBACK", version="1.0.0", description="rollback needs approval",
        tools=["rollback"], owner="test")
def rollback_needs_approval(ctx: PolicyContext) -> PolicyResult:
    return PolicyResult.require_approval("PRODUCTION_ROLLBACK_REQUIRES_APPROVAL")


@policy(id="TEST-SCALE", version="1.0.0", description="max 4 replicas without approval",
        tools=["scale"], owner="test")
def scale_limit(ctx: PolicyContext) -> PolicyResult:
    if ctx.arguments["replicas"] > 10:
        return PolicyResult.deny("REPLICAS_ABOVE_HARD_LIMIT")
    if ctx.arguments["replicas"] > 4:
        return PolicyResult.require_approval("REPLICAS_ABOVE_4")
    return PolicyResult.allow()


@policy(id="TEST-BROKEN", version="1.0.0", description="crashes", tools=["broken"], owner="test")
def broken(ctx: PolicyContext) -> PolicyResult:
    raise RuntimeError("bug in policy")
