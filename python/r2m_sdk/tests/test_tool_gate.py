from datetime import datetime, timedelta, timezone

import pytest
from policies_fixture import broken, rollback_needs_approval, scale_limit

from r2m import (ApprovalRequired, ConfigurationError, GrantInvalid, PolicyActivationError, PolicyDenied,
                 resume_action)


@pytest.fixture
def tools(client):
    client.register_policies(rollback_needs_approval, scale_limit, broken)
    calls = []

    @client.tool("health")
    def health():
        calls.append("health")
        return {"status": "ok"}

    @client.tool("rollback", risk="high", policies=[rollback_needs_approval])
    def rollback(target_version: str):
        calls.append(("rollback", target_version))
        return {"version": target_version}

    @client.tool("scale", risk="high", policies=[scale_limit])
    def scale(replicas: int):
        calls.append(("scale", replicas))
        return {"replicas": replicas}

    @client.tool("broken", risk="high", policies=[broken])
    def broken_tool():
        calls.append("broken")

    return calls, health, rollback, scale, broken_tool


def test_unguarded_tool_is_observed_only(client, platform, tools):
    calls, health, *_ = tools
    with client.execution():
        assert health() == {"status": "ok"}
    client.flush()
    assert calls == ["health"]
    assert platform.events_of("tool.call")[0]["attributes"]["coverage"] == "observed"
    assert not platform.decisions


def test_allowed_guarded_tool_executes_with_grant_and_reports(client, platform, tools):
    calls, _, _, scale, _ = tools
    with client.execution():
        assert scale(3) == {"replicas": 3}
    client.flush()
    assert calls == [("scale", 3)]
    action = next(iter(platform.actions.values()))
    assert action.executed and action.results[0]["outcome"] == "succeeded"
    decision = platform.events_of("policy.decision")[0]["attributes"]
    assert decision["authorization_outcome"] == "ALLOW"
    assert decision["tool_action_id"] == action.action_id
    assert platform.events_of("tool.call")[0]["attributes"]["coverage"] == "enforced"


def test_hard_deny_never_executes(client, platform, tools):
    calls, _, _, scale, _ = tools
    with client.execution():
        with pytest.raises(PolicyDenied) as err:
            scale(50)
    assert err.value.reason_codes == ("REPLICAS_ABOVE_HARD_LIMIT",)
    assert calls == []
    client.flush()
    assert platform.events_of("span")[0]["status"] == "denied"


def test_rollback_requires_exact_action_approval_then_runs_once(client, platform, tools):
    calls, _, rollback, _, _ = tools
    with client.execution("approval") as run:
        with pytest.raises(ApprovalRequired) as err:
            rollback("2.0")
        run.suspend()  # agent moves to WAIT_APPROVAL
    assert calls == []
    action_id = err.value.action_id
    client.flush()
    assert not platform.events_of("execution.ended")  # left open while waiting

    # Approval for a *different* argument set must not authorise this one.
    platform.approve_action(action_id)
    with client.execution(execution_id=run.execution_id, resume=True):
        with resume_action(action_id), pytest.raises(PolicyDenied) as wrong:
            rollback("1.0")
    assert "ACTION_BINDING_MISMATCH" in wrong.value.reason_codes

    with client.execution(execution_id=run.execution_id, resume=True):
        with resume_action(action_id):
            assert rollback("2.0") == {"version": "2.0"}
    assert calls == [("rollback", "2.0")]

    # One grant per approval: a replayed resume is denied.
    with client.execution(execution_id=run.execution_id, resume=True):
        with resume_action(action_id), pytest.raises(PolicyDenied) as replay:
            rollback("2.0")
    assert "APPROVAL_CONSUMED" in replay.value.reason_codes
    assert calls == [("rollback", "2.0")]


def test_rejected_approval_denies(client, platform, tools):
    calls, _, rollback, _, _ = tools
    with client.execution() as run:
        with pytest.raises(ApprovalRequired) as err:
            rollback("2.0")
    platform.reject_action(err.value.action_id)
    with client.execution(execution_id=run.execution_id, resume=True):
        with resume_action(err.value.action_id), pytest.raises(PolicyDenied) as denied:
            rollback("2.0")
    assert "APPROVAL_REJECTED" in denied.value.reason_codes
    assert calls == []


def test_platform_unreachable_fails_closed(client, platform, tools):
    calls, _, _, scale, _ = tools
    platform.down = True
    with client.execution():
        with pytest.raises(PolicyDenied) as err:
            scale(2)
    assert err.value.reason_codes[0] == "AUTHORIZATION_UNAVAILABLE"
    assert calls == []


def test_unapproved_policy_hash_denied_by_server(client, platform, tools):
    calls, _, _, scale, _ = tools
    platform.revoke_policy(scale_limit.artifact_hash)
    with client.execution():
        with pytest.raises(PolicyDenied) as err:
            scale(2)
    assert err.value.reason_codes == ("POLICY_NOT_APPROVED:TEST-SCALE",)
    assert calls == []


def test_crashing_policy_denies(client, tools):
    calls, *_, broken_tool = tools
    with client.execution():
        with pytest.raises(PolicyDenied) as err:
            broken_tool()
    assert err.value.reason_codes == ("POLICY_EVALUATION_ERROR",)
    assert calls == []


@pytest.mark.parametrize("tamper,code", [
    ({"arguments_hash": "sha256:other"}, "GRANT_BAD_SIGNATURE"),
    ({"signature": "0" * 64}, "GRANT_BAD_SIGNATURE"),
])
def test_tampered_grant_refused(client, platform, tools, tamper, code):
    calls, _, _, scale, _ = tools
    platform.tamper_grant = tamper
    with client.execution():
        with pytest.raises(GrantInvalid) as err:
            scale(2)
    assert err.value.reason_codes == (code,)
    assert calls == []


def test_grant_binding_checks(client, platform):
    from r2m.approvals import ActionGrant, GrantVerifier, sign_grant
    body = {"grant_id": "g", "action_id": "a", "decision_id": "d", "customer_org_id": "c", "deployment_id": "dep",
            "policy_revision_ids": ["r"], "tool": "scale", "arguments_hash": "h", "execution_id": "e",
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(), "nonce": "n1"}
    grant = ActionGrant.from_dict({**body, "signature": sign_grant(body, "k")})
    v = GrantVerifier("k")
    kw = dict(tool="scale", args_hash="h", execution_id="e", customer_org_id="c", deployment_id="dep",
              action_id="a")
    with pytest.raises(GrantInvalid, match="GRANT_ARGUMENTS_MISMATCH"):
        v.verify(grant, **{**kw, "args_hash": "x"})
    with pytest.raises(GrantInvalid, match="GRANT_EXPIRED"):
        v.verify(grant, **kw, now=datetime.now(timezone.utc) + timedelta(minutes=5))
    v.verify(grant, **kw)
    with pytest.raises(GrantInvalid, match="GRANT_NONCE_REUSED"):
        v.verify(grant, **kw)


def test_tool_must_be_declared_by_policy(client):
    with pytest.raises(ConfigurationError):
        client.tool("restart", policies=[scale_limit])


def test_tool_failure_reported(client, platform):
    client.register_policies(scale_limit)

    @client.tool("scale", risk="high", policies=[scale_limit])
    def scale(replicas: int):
        raise TimeoutError("infra timeout")

    with client.execution():
        with pytest.raises(TimeoutError):
            scale(2)
    action = next(iter(platform.actions.values()))
    assert action.results[0]["outcome"] == "failed"
    assert action.results[0]["error_class"] == "TimeoutError"


async def test_async_guarded_tool(client, platform):
    client.register_policies(scale_limit)

    @client.tool("scale", risk="high", policies=[scale_limit])
    async def scale(replicas: int):
        return replicas

    async with client.execution():
        assert await scale(2) == 2
    assert next(iter(platform.actions.values())).executed


def test_proposed_build_cannot_act(platform, client, tools):
    calls, _, _, scale, _ = tools
    platform.deployments[client.deployment_id] = "proposed"
    with client.execution():
        with pytest.raises(PolicyDenied) as err:
            scale(2)
    assert err.value.reason_codes == ("DEPLOYMENT_NOT_ACTIVE",)
    assert calls == []


def test_dropping_a_governing_policy_is_denied(client, platform, tools):
    ran = []

    @client.tool("scale", risk="high")  # a build that "forgot" CAPACITY's binding
    def scale(replicas: int):
        ran.append(replicas)

    with client.execution():
        with pytest.raises(PolicyDenied) as err:
            scale(2)
    assert err.value.reason_codes == ("GOVERNING_POLICY_NOT_CITED:TEST-SCALE",)
    assert ran == []


def test_grant_claim_is_single_use(client, platform, tools):
    _, _, _, scale, _ = tools
    with client.execution() as run:
        scale(2)
    assert platform.claim_grant(run.execution_id, "scale") is not None
    assert platform.claim_grant(run.execution_id, "scale") is None
