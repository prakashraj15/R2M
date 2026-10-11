"""DEPLOY-001: a production rollback requires exact-action human approval."""
import re

from r2m import PolicyContext, PolicyResult, policy

_VERSION = re.compile(r"^v\d+\.\d+(\.\d+)?$")


@policy(id="DEPLOY-001", version="1.0.0", owner="atlas-applied-ai",
        description="Production rollback requires exact-action human approval",
        tools=["rollback_deployment"], scope="production")
def DEPLOY_001(ctx: PolicyContext) -> PolicyResult:
    target = str(ctx.arguments.get("target_version", ""))
    if not _VERSION.match(target):
        return PolicyResult.deny("INVALID_TARGET_VERSION", "target_version must look like v2.0")
    if ctx.environment == "production":
        return PolicyResult.require_approval("PRODUCTION_ROLLBACK_REQUIRES_APPROVAL",
                                             f"rollback to {target} needs a customer security approval")
    return PolicyResult.allow("NON_PRODUCTION_ROLLBACK")
