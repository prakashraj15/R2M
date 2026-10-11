import ast
from pathlib import Path

import pytest
from r2m.testing import FakePlatform

from mock_agent import evals
from mock_agent.build import FAULTY_VERSION, SAFE_VERSION, build
from mock_agent.llm import parse_intent
from mock_agent.sandbox import ROLLBACK_HISTORY, TOKEN, FakeInsights, Sandbox

PKG = Path(__file__).parents[1]


def test_agent_imports_only_public_sdk():
    for f in PKG.rglob("*.py"):
        if "tests" in f.relative_to(PKG).parts:
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
            for m in mods:
                assert m.split(".")[0] not in ("r2m_platform", "asyncpg", "fastapi"), f"{f.name} imports {m}"
                if m.startswith("r2m."):
                    assert m in ("r2m.testing",) and f.name == "sandbox.py", f"{f.name} imports private {m}"


def test_build_identity_is_stable_and_variant_specific():
    assert build(SAFE_VERSION) == build(SAFE_VERSION)
    assert build(SAFE_VERSION).source_digest == build(FAULTY_VERSION).source_digest
    assert build(SAFE_VERSION).artifact_digest != build(FAULTY_VERSION).artifact_digest
    with pytest.raises(ValueError):
        build("latest")


@pytest.mark.parametrize("msg,kind,params", [
    ("Roll back payments-api to v2.0", "rollback", {"target_version": "v2.0"}),
    ("scale payments-api to 6 replicas", "scale", {"desired_replicas": 6}),
    ("please restart it", "restart", {}),
    ("continue", "resume", {}),
    ("run the faulty build rollback", "fault_injection", {}),
    ("fix it", "remediate", {}),
    ("how is it?", "observe", {}),
])
def test_intents(msg, kind, params):
    intent = parse_intent(msg, "healthy")
    assert (intent.kind, intent.params) == (kind, params)


def test_healthy_observation_traces_without_mutation():
    sb = Sandbox("healthy")
    out = sb.say("How is payments-api doing?")
    assert out["decision"] is None and not sb.world.actions
    assert out["steps"] == ["RECEIVED", "OBSERVE", "DIAGNOSE", "REPORT"]
    spans = sb.platform.events_of("span")
    assert {s["attributes"].get("component") for s in spans} >= {"orchestrator", "sim-llm", "get_service_health"}
    assert all(u["attributes"]["cost_source"] == "simulated" for u in sb.platform.events_of("usage"))
    assert not sb.platform.rejected_events


def test_keewano_history_changes_recommendation_but_not_policy():
    without = Sandbox("degraded").say("fix it")
    with_history = Sandbox("degraded", insights=FakeInsights(ROLLBACK_HISTORY)).say("fix it")
    assert (without["proposal"]["tool"], without["proposal"]["source"]) == ("restart_service", "deterministic")
    assert "intelligence unavailable" in without["reply"] and without["insight"]["status"] == "unavailable"
    assert (with_history["proposal"]["tool"], with_history["proposal"]["source"]) == ("rollback_deployment", "keewano")
    assert with_history["decision"] == "REQUIRE_APPROVAL"  # Keewano can't bypass DEPLOY-001


def test_insight_event_emitted():
    sb = Sandbox("degraded", insights=FakeInsights(ROLLBACK_HISTORY))
    sb.say("fix it")
    insight = sb.platform.events_of("insight")[0]["attributes"]
    assert insight["proposed_action"] == "rollback_deployment" and insight["keewano_informed"] is True
    assert insight["sample_count"] == 64 and insight["insight_id"]


def test_untrusted_insight_junk_is_ignored():
    junk = {"sample_count": "lots", "recommendations": [{"remediation": "delete_database", "samples": 999,
                                                         "successes": 999}, "not-a-dict"]}
    out = Sandbox("degraded", insights=FakeInsights(junk)).say("fix it")
    assert out["proposal"]["source"] == "deterministic" and out["proposal"]["tool"] == "restart_service"


def test_approval_resume_runs_in_same_execution_exactly_once():
    sb = Sandbox("approval")
    first = sb.say("Roll back payments-api to v2.0")
    assert first["decision"] == "REQUIRE_APPROVAL" and sb.world.get_service()["deployment_version"] == "v2.1"
    early = sb.say("continue")  # not approved yet
    assert early["decision"] == "REQUIRE_APPROVAL" and early["execution_id"] == first["execution_id"]
    sb.platform.approve_action(first["action_id"])
    done = sb.say("continue")
    assert done["execution_id"] == first["execution_id"] and done["decision"] == "ALLOW" and done["verified"]
    assert sb.world.get_service()["deployment_version"] == "v2.0"
    action = sb.platform.actions[first["action_id"]]
    assert action.results[-1]["phase"] == "verified"
    ended = sb.platform.events_of("execution.ended")
    assert [e["execution_id"] for e in ended] == [first["execution_id"]]


def test_rejected_approval_reports_denial_and_clears_memory():
    sb = Sandbox("approval")
    first = sb.say("Roll back payments-api to v2.0")
    sb.platform.reject_action(first["action_id"])
    out = sb.say("continue")
    assert out["decision"] == "DENY" and "APPROVAL_REJECTED" in out["reasons"]
    assert sb.say("continue")["reply"].startswith("There is no action waiting")


def test_unreleased_build_is_denied_with_hint():
    sb = Sandbox("degraded", platform=FakePlatform(grant_key=TOKEN, auto_deploy=False))
    out = sb.say("restart payments-api")
    assert out["decision"] == "DENY" and "DEPLOYMENT_NOT_ACTIVE" in out["reasons"]
    assert "has not been released" in out["reply"] and out["build"]["deployment_status"] == "proposed"
    assert not sb.world.actions


def test_fault_injection_is_vendor_only_and_refused_by_infrastructure():
    customer = Sandbox("faulty", roles=("customer_security",))
    out = customer.say("run the faulty build rollback")
    assert not customer.world.actions and "vendor-only" in out["reply"]
    vendor = Sandbox("faulty", roles=("vendor_developer",))
    out = vendor.say("run the faulty build rollback")
    assert out["reasons"] == ["INFRASTRUCTURE_REFUSED_NO_GRANT"]
    assert vendor.world.get_service()["deployment_version"] == "v2.1"
    assert vendor.world.incidents[0]["severity"] == "critical"
    tool_call = [e for e in vendor.platform.events_of("tool.call") if e["attributes"]["tool"] == "rollback_deployment"]
    assert tool_call[0]["attributes"]["coverage"] == "observed"


def test_safe_build_passes_all_mandatory_evals():
    runs = evals.run_all(SAFE_VERSION)
    assert evals.mandatory_failures(runs) == []
    assert {r["suite_key"] for r in runs} >= {"opspilot.policy_regression"}
    assert all(r["build"]["artifact_digest"] == build(SAFE_VERSION).artifact_digest for r in runs)


def test_faulty_build_fails_mandatory_evals():
    failures = evals.mandatory_failures(evals.run_all(FAULTY_VERSION))
    assert "opspilot.policy_regression:rollback_tool_is_gated" in failures
    assert "opspilot.policy_regression:rollback_requires_approval" in failures
