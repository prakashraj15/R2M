"""Live (OpenAI) mode against a scripted fake Chat Completions server: no network, no real key."""
import json

import httpx
import pytest

from mock_agent.sandbox import ROLLBACK_HISTORY, FakeInsights, Sandbox


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)


def call(name, **args):
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedOpenAI:
    """Replays assistant messages in order and records every request body."""

    def __init__(self, *steps, status=200):
        self.steps = list(steps)
        self.requests = []
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test-not-real"
        body = json.loads(request.content)
        self.requests.append(body)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"code": "rate_limit_exceeded"}})
        step = self.steps.pop(0)
        message = {"role": "assistant", "content": step} if isinstance(step, str) else \
            {"role": "assistant", "content": None, "tool_calls": step}
        return httpx.Response(200, json={"choices": [{"message": message}],
                                         "usage": {"prompt_tokens": 1000, "completion_tokens": 100}})

    def sandbox(self, scenario, **kw):
        return Sandbox(scenario, llm_mode="openai", openai_transport=httpx.MockTransport(self), **kw)


def test_live_observation_reads_and_replies_without_mutation():
    llm = ScriptedOpenAI([call("get_service_health")], "payments-api is healthy on v2.1 (0.3% errors).")
    sb = llm.sandbox("healthy")
    out = sb.say("how is payments-api?")
    assert out["mode"] == "live" and out["reply"].startswith("payments-api is healthy")
    assert out["steps"] == ["RECEIVED", "OBSERVE", "REPORT"] and not sb.world.actions
    usage = sb.platform.events_of("usage")
    assert [u["attributes"]["provider"] for u in usage] == ["openai", "openai"]
    assert all(u["attributes"]["cost_source"] == "estimated" for u in usage)
    assert usage[0]["attributes"]["amount_usd"] == pytest.approx(0.00021)  # gpt-4o-mini list price
    assert {s["attributes"].get("component") for s in sb.platform.events_of("span")} >= {"openai-llm"}
    # The tool result went back to the model, redacted.
    tool_msg = llm.requests[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "v2.1" in tool_msg["content"]


def test_live_keewano_informed_rollback_still_needs_approval_then_resumes_without_model():
    llm = ScriptedOpenAI(
        [call("get_service_health")],
        [call("read_logs", limit=20)],
        [call("query_remediation_history", incident_category="post_deploy_errors")],
        [call("rollback_deployment", target_version="v2.0", incident_category="post_deploy_errors",
              rationale="Keewano: rollback recovered 35/38 similar incidents")],
        "Rollback to v2.0 needs approval from Meridian security in R2M; then say continue.",
        "Rolled back to v2.0; errors fell from 7.8% to 0.4%.",
    )
    sb = llm.sandbox("degraded", insights=FakeInsights(ROLLBACK_HISTORY))
    out = sb.say("payments-api is failing, fix it")
    assert out["decision"] == "REQUIRE_APPROVAL" and out["proposal"]["source"] == "keewano"
    assert out["steps"][:4] == ["RECEIVED", "OBSERVE", "OPTIONAL_KEEWANO_HISTORY", "DIAGNOSE"]
    assert llm.requests[-1]["tool_choice"] == "none"  # after the action the model may only talk
    insight = sb.platform.events_of("insight")[0]["attributes"]
    assert insight["keewano_informed"] is True and insight["proposed_action"] == "rollback_deployment"
    assert sb.world.get_service()["deployment_version"] == "v2.1"

    sb.platform.approve_action(out["action_id"])
    n_requests = len(llm.requests)
    done = sb.say("continue")
    assert done["decision"] == "ALLOW" and done["execution_id"] == out["execution_id"]
    # The approved action runs with its stored arguments; the model is asked only to narrate the result.
    assert len(llm.requests) == n_requests + 1 and "tools" not in llm.requests[-1]
    assert done["reply"] == "Rolled back to v2.0; errors fell from 7.8% to 0.4%."
    assert sb.world.get_service()["deployment_version"] == "v2.0"


def test_live_model_cannot_get_raw_logs_or_act_twice():
    llm = ScriptedOpenAI(
        [call("read_logs", limit=10, include_raw=True)],
        [call("restart_service", rationale="restart", incident_category="post_deploy_errors")],
        "Restarted; still degraded.",
    )
    sb = llm.sandbox("degraded")
    sb.say("restart payments-api")
    raw_result = json.loads(llm.requests[1]["messages"][-1]["content"])
    assert raw_result == {"error": "denied_by_r2m", "reasons": ["RAW_LOG_ACCESS_FORBIDDEN"]}
    assert len([a for a in sb.world.actions if a["authorized"]]) == 1


def test_live_hard_limit_denial_reported_to_model():
    llm = ScriptedOpenAI(
        [call("scale_instances", desired_replicas=40, rationale="more capacity", incident_category="capacity_pressure")],
        "R2M denied scaling to 40: REPLICAS_ABOVE_HARD_LIMIT.",
    )
    sb = llm.sandbox("degraded")
    out = sb.say("scale to 40 replicas")
    assert out["decision"] == "DENY" and out["reasons"] == ["REPLICAS_ABOVE_HARD_LIMIT"]
    told = json.loads(llm.requests[1]["messages"][-1]["content"])
    assert told["outcome"] == "denied" and told["changed"] is False


def test_model_outage_falls_back_to_deterministic_agent():
    llm = ScriptedOpenAI(status=429)
    sb = llm.sandbox("degraded")
    out = sb.say("fix it")
    assert out["mode"] == "simulated-fallback" and "Live model unavailable" in out["reply"]
    assert out["proposal"]["tool"] == "restart_service" and out["decision"] == "ALLOW"


def test_secrets_in_user_message_are_redacted_before_the_model():
    llm = ScriptedOpenAI("ok")
    llm.sandbox("healthy").say("my password=hunter2 and card 4111 1111 1111 1111, status?")
    sent = json.dumps(llm.requests[0])
    assert "hunter2" not in sent and "4111 1111 1111 1111" not in sent


def test_without_key_runs_simulated(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    out = Sandbox("healthy", llm_mode="openai").say("status?")
    assert out["mode"] == "simulated"


def test_live_fault_demo_vendor_gets_ungated_tool_refused_by_infrastructure():
    llm = ScriptedOpenAI(
        [call("rollback_deployment", target_version="v2.0", incident_category="post_deploy_errors",
              rationale="fault-injection test")],
        "The ungated rollback was refused by the infrastructure; R2M opened a critical incident.",
    )
    sb = llm.sandbox("faulty", roles=("vendor_developer",))
    out = sb.say("run the faulty build rollback")
    assert out["reasons"] == ["INFRASTRUCTURE_REFUSED_NO_GRANT"] and out["proposal"]["source"] == "fault_injection"
    assert sb.world.get_service()["deployment_version"] == "v2.1" and sb.world.incidents
    assert any("faulty-1.0" in m["content"] for m in llm.requests[0]["messages"] if m["role"] == "system")


def test_live_fault_scenario_customer_only_has_gated_tools():
    llm = ScriptedOpenAI(
        [call("rollback_deployment", target_version="v2.0", incident_category="post_deploy_errors", rationale="x")],
        "Rollback needs approval.",
    )
    sb = llm.sandbox("faulty", roles=("customer_ops",))
    out = sb.say("run the faulty build rollback")
    assert out["decision"] == "REQUIRE_APPROVAL" and not sb.world.unauthorized_attempts


def test_history_is_dropped_when_the_world_changed():
    llm = ScriptedOpenAI("Rolled back already.", "payments-api is degraded on v2.1.")
    sb = llm.sandbox("approval")
    sb.say("status?")
    sb.world.services["payments-api"]["deployment_version"] = "v9.9"  # e.g. a scenario reset
    sb.say("status again?")
    roles = [m["role"] for m in llm.requests[1]["messages"]]
    assert roles == ["system", "user"]  # the stale exchange was not replayed


def test_history_kept_while_world_unchanged():
    llm = ScriptedOpenAI("It is degraded.", "Still degraded.")
    sb = llm.sandbox("degraded")
    sb.say("status?")
    sb.say("and now?")
    assert [m["role"] for m in llm.requests[1]["messages"]] == ["system", "user", "assistant", "user"]


def test_conversations_are_per_person_but_pending_approval_is_shared():
    llm = ScriptedOpenAI(
        [call("rollback_deployment", target_version="v2.0", incident_category="post_deploy_errors", rationale="r")],
        "Needs approval.", "Hello Atlas dev.",
    )
    ops = llm.sandbox("approval", roles=("customer_ops",))
    first = ops.say("Roll back payments-api to v2.0")
    dev = Sandbox("approval", roles=("vendor_developer",), llm_mode="openai",
                  openai_transport=httpx.MockTransport(llm), platform=ops.platform, world=ops.world)
    ctx = dev.context()
    ctx["actor"]["email"] = "dev@atlas.demo"
    from mock_agent.agent import run_turn
    client = dev.client()
    try:
        run_turn(client, "hi", "approval", ctx)
    finally:
        client.close()
    sent = llm.requests[-1]["messages"]
    assert [m["role"] for m in sent if m["role"] != "system"] == ["user"]  # ops' chat is not replayed
    assert any("awaits approval" in m["content"] for m in sent if m["role"] == "system")  # pending is shared
    assert first["decision"] == "REQUIRE_APPROVAL"


def test_tool_error_is_reported_not_crashing_the_turn():
    llm = ScriptedOpenAI(
        [call("rollback_deployment", target_version="previous_release", incident_category="unknown", rationale="x")],
        "The rollback failed: unknown release.",
    )
    sb = llm.sandbox("faulty", roles=("vendor_developer",))
    out = sb.say("run the faulty build rollback")
    assert out["decision"] == "FAILED" and out["reasons"] == ["TOOL_ERROR:ValueError"]
    told = json.loads(llm.requests[1]["messages"][-1]["content"])
    assert told["outcome"] == "failed" and told["changed"] is False
    assert sb.world.get_service()["deployment_version"] == "v2.1"


def test_open_ended_fix_consults_keewano_before_any_action():
    llm = ScriptedOpenAI(
        [call("restart_service", rationale="errors", incident_category="post_deploy_errors")],  # skips history
        [call("rollback_deployment", target_version="v2.0", incident_category="post_deploy_errors",
              rationale="history: rollback 35/38")],
        "Rollback needs approval.",
    )
    sb = llm.sandbox("degraded", insights=FakeInsights(ROLLBACK_HISTORY))
    out = sb.say("payments-api is throwing errors, fix it")
    first_result = json.loads(llm.requests[1]["messages"][-1]["content"])
    assert first_result["not_executed"] is True and first_result["supported"] is True
    assert not sb.world.actions  # the restart never ran
    assert out["proposal"]["tool"] == "rollback_deployment" and out["proposal"]["source"] == "keewano"
    assert "OPTIONAL_KEEWANO_HISTORY" in out["steps"]


def test_named_action_is_not_forced_through_history():
    llm = ScriptedOpenAI([call("restart_service", rationale="asked", incident_category="unknown")], "Restarted.")
    sb = llm.sandbox("degraded", insights=FakeInsights(ROLLBACK_HISTORY))
    out = sb.say("restart payments-api")
    assert out["decision"] == "ALLOW" and "OPTIONAL_KEEWANO_HISTORY" not in out["steps"]
