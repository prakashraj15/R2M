"""Test-only stand-in for mock_agent.agent, driving the platform through the real r2m SDK.

Messages: "rollback" | "resume <action_id> <execution_id>" | "bypass" (unguarded mutation, the faulty-build path).
"""
from r2m import ApprovalRequired, PolicyDenied, PolicyResult, R2MClient, current_execution, policy, resume_action


@policy(id="DEPLOY-001", version="1.0.0", description="Production rollback requires exact-action approval",
        tools=["rollback_deployment"], owner="atlas")
def deploy_001(ctx):
    if ctx.environment == "production":
        return PolicyResult.require_approval("PRODUCTION_ROLLBACK_REQUIRES_APPROVAL")
    return PolicyResult.allow()


BUILD = {"build_version": "e2e-1.0", "source_digest": "sha256:" + "1" * 64, "artifact_digest": "sha256:" + "e" * 64}
ROLLBACK = {"deployment_version": "v2.0", "previous_version": "v2.1", "error_rate_pct": 0.4, "health_status": "healthy"}


def handle_message(message: str, scenario: str, context: dict) -> dict:
    world = context["world"]
    client = R2MClient(token=context["sdk_token"], agent_slug="opspilot",
                       vendor_org_id=context["vendor_org_id"], customer_org_id=context["customer_org_id"],
                       environment=context["environment"], base_url=context["api_url"], background=False)
    reg = client.register_agent(
        name="OpsPilot", **BUILD,
        components=[{"component_key": "orchestrator", "kind": "orchestrator", "label": "OpsPilot"},
                    {"component_key": "rollback_deployment", "kind": "tool", "label": "rollback_deployment"}],
        edges=[{"source": "orchestrator", "target": "rollback_deployment", "edge_kind": "calls"}])
    client.register_policies(deploy_001)

    @client.tool("rollback_deployment", risk="high", policies=[deploy_001])
    def rollback_deployment(target_version: str):
        return world.apply_action("rollback_deployment", ROLLBACK, current_execution().execution_id)

    verb, *rest = message.split()
    out = {"deployment_status": reg["deployment_status"]}
    try:
        with client.execution(scenario, execution_id=rest[1] if verb == "resume" else None,
                              resume=verb == "resume") as run:
            out.update(execution_id=run.execution_id, trace_id=run.trace_id)
            if verb == "rollback":
                out["result"] = rollback_deployment("v2.0")
            elif verb == "resume":
                with resume_action(rest[0]):
                    out["result"] = rollback_deployment("v2.0")
            elif verb == "bypass":  # no SDK gate at all
                out["result"] = world.apply_action("rollback_deployment", ROLLBACK, run.execution_id)
    except ApprovalRequired as e:
        out.update(decision="REQUIRE_APPROVAL", action_id=e.action_id, approval_id=e.approval_id)
    except PolicyDenied as e:
        out.update(decision="DENY", reasons=list(e.reason_codes))
    client.close()
    return out
