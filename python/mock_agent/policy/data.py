"""DATA-001: never return secrets or unredacted customer identifiers from logs.

Enforced twice: this pre-execution gate refuses raw log access and oversized reads, and the
read_logs tool itself redacts every line before returning it.
"""
from r2m import PolicyContext, PolicyResult, policy

MAX_LINES = 200


@policy(id="DATA-001", version="1.0.0", owner="atlas-applied-ai",
        description="Do not return secrets or unredacted customer identifiers from logs",
        tools=["read_logs"], scope="production")
def DATA_001(ctx: PolicyContext) -> PolicyResult:
    if ctx.arguments.get("include_raw"):
        return PolicyResult.deny("RAW_LOG_ACCESS_FORBIDDEN", "only redacted logs may be returned")
    if int(ctx.arguments.get("limit", 0)) > MAX_LINES:
        return PolicyResult.deny("LOG_READ_TOO_LARGE", f"max {MAX_LINES} lines")
    return PolicyResult.allow("REDACTED_LOGS_ONLY")
