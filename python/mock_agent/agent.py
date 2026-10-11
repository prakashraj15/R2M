"""Entry point called by the platform's demo route (docs/API_CONTRACT.md "Agent hook").

    handle_message(message: str, scenario: str, context: dict) -> dict

Runs in a worker thread. Builds an R2M client per call, registers this build and its policies,
runs one deterministic workflow turn, flushes traces and returns a JSON-able dict.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from r2m import R2MClient, TransportError

from . import openai_llm
from .build import AGENT_DESCRIPTION, AGENT_NAME, AGENT_SLUG, COMPONENTS, EDGES, SAFE_VERSION, build
from .live import LiveWorkflow, QuietLLM
from .llm import SimulatedLLM
from .memory import ConversationMemory
from .policy import ALL_POLICIES
from .scenarios import FAULT_INJECTION_ROLES, SCENARIOS
from .tools import make_tools
from .workflow import Workflow

log = logging.getLogger("mock_agent")


def make_client(context: dict[str, Any], **overrides: Any) -> R2MClient:
    # The platform hands the in-process agent its own per-customer token; the env var is for out-of-process runs.
    cfg = dict(token=context.get("sdk_token") or os.environ["SDK_INGEST_TOKEN"], agent_slug=AGENT_SLUG, vendor_org_id=context["vendor_org_id"],
               customer_org_id=context["customer_org_id"], environment=context["environment"],
               base_url=context["api_url"], background=False)
    cfg.update(overrides)
    return R2MClient(**cfg)


def run_turn(client: R2MClient, message: str, scenario: str, context: dict[str, Any], *,
             build_version: str = SAFE_VERSION) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        return {"reply": f"Unknown scenario {scenario!r}.", "decision": None, "scenario": scenario}
    b = build(build_version)
    try:
        reg = client.register_agent(name=AGENT_NAME, description=AGENT_DESCRIPTION, **b.register_kwargs(),
                                    components=COMPONENTS, edges=EDGES)
        client.register_policies(*ALL_POLICIES)
    except TransportError as exc:
        log.warning("R2M registration failed: %s", exc)
        return {"reply": "The R2M platform is unreachable, so OpsPilot will not act (fail closed).",
                "decision": "DENY", "reasons": ["PLATFORM_UNREACHABLE"], "scenario": scenario}
    client.heartbeat(component="orchestrator", build_version=b.version)

    world = context["world"]
    roles = set((context.get("actor") or {}).get("roles") or [])
    can_fault_inject = bool(roles & FAULT_INJECTION_ROLES)
    common = dict(scenario=scenario, build=b, deployment_status=reg.get("deployment_status", "unknown"),
                  can_fault_inject=can_fault_inject,
                  fault_tools=make_tools(client, world, fault_injection=True) if can_fault_inject else None)
    tools = make_tools(client, world, fault_injection=b.fault_injection)
    memory = ConversationMemory(client, context["customer_org_id"])

    mode = llm_mode(context)
    if mode == "openai":
        try:
            chat = openai_llm.OpenAIChat(client, transport=context.get("openai_transport"))
        except openai_llm.LiveModelError as exc:
            log.warning("live model unavailable, using simulated: %s", exc)
        else:
            try:
                return LiveWorkflow(client, tools, QuietLLM(), memory, context.get("insights"), chat=chat,
                                    **common).handle(message)
            finally:
                chat.close()
    out = Workflow(client, tools, SimulatedLLM(client), memory, context.get("insights"), **common).handle(message)
    out.setdefault("mode", "simulated")
    return out


def llm_mode(context: dict[str, Any]) -> str:
    """openai when configured (OPSPILOT_LLM_MODE overrides); evals and the sandbox pin 'simulated'."""
    mode = context.get("llm_mode") or os.environ.get("OPSPILOT_LLM_MODE", "").strip().lower()
    if mode in ("openai", "simulated"):
        return mode
    return "openai" if openai_llm.configured() else "simulated"


def handle_message(message: str, scenario: str, context: dict[str, Any]) -> dict[str, Any]:
    client = make_client(context)
    try:
        return run_turn(client, message, scenario, context)
    finally:
        client.close()
