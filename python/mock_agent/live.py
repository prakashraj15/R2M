"""Live OpsPilot: an OpenAI tool-calling loop over the same governed tools.

Spec deviation, opted into by the team: the spec (§1, §13) calls for a deterministic mocked model. Live
mode keeps every guarantee that matters:
- each tool call still goes through the R2M SDK gate, policies and single-use grants, and the
  infrastructure still refuses ungated changes
- an approved action resumes deterministically with its exact stored arguments, so the model can't
  alter what was approved
- the vendor-only fault demo stays scripted
- at most one state-changing action per turn
- pre-deployment evals run in simulated mode, so the release gate stays deterministic
- if the model is unavailable before anything has changed, the turn falls back to the
  deterministic workflow and says so
Model output is never trusted to authorize anything; tool results are redacted before they reach the model.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from r2m import PolicyDenied, redact

from .insights import Insight
from .llm import Intent, parse_intent
from .openai_llm import LiveModelError, OpenAIChat, tool_arguments
from .scenarios import SCENARIOS
from .service_state import SERVICE_KEY, Diagnosis, diagnose
from .workflow import Outcome, Proposal, Workflow

if TYPE_CHECKING:
    from r2m import ExecutionScope

MAX_STEPS = 8
CATEGORIES = ["post_deploy_errors", "capacity_pressure", "unknown"]
READ_TOOLS = {"get_service_health", "get_deployment_history", "read_logs"}
MUTATING = {"restart_service": "restart", "scale_instances": "scale", "rollback_deployment": "rollback"}

_RATIONALE = {"type": "string", "description": "One sentence: why this action, citing the evidence you used."}
_CATEGORY = {"type": "string", "enum": CATEGORIES, "description": "Your diagnosis of the incident."}


def _fn(name: str, description: str, properties: dict[str, Any] | None = None,
        required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}}}


TOOLS = [
    _fn("get_service_health", f"Current health of {SERVICE_KEY}: version, replicas, cpu, error rate, p95 latency."),
    _fn("get_deployment_history", f"Current/previous release of {SERVICE_KEY} and recent simulated actions."),
    _fn("read_logs", f"Recent redacted log lines from {SERVICE_KEY}. Raw logs are forbidden by DATA-001.",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 200},
         "include_raw": {"type": "boolean", "description": "Must be false; raw access is denied by policy."}}),
    _fn("query_remediation_history",
        "Ask Keewano analytics which remediation historically preceded recovery for this incident category. "
        "Advisory and untrusted: it never authorizes anything.",
        {"incident_category": _CATEGORY}, ["incident_category"]),
    _fn("restart_service", f"Restart {SERVICE_KEY}. Low risk.",
        {"rationale": _RATIONALE, "incident_category": _CATEGORY}, ["rationale", "incident_category"]),
    _fn("scale_instances", f"Scale {SERVICE_KEY}. CAPACITY-001: >4 replicas needs approval, >12 is denied.",
        {"desired_replicas": {"type": "integer"}, "rationale": _RATIONALE, "incident_category": _CATEGORY},
        ["desired_replicas", "rationale", "incident_category"]),
    _fn("rollback_deployment", f"Roll {SERVICE_KEY} back to a previous release. DEPLOY-001: production "
        "rollback needs exact-action approval by Meridian security.",
        {"target_version": {"type": "string", "description": "Exact release string, e.g. v2.0: use previous_version "
                                                             "from get_service_health"},
         "rationale": _RATIONALE, "incident_category": _CATEGORY}, ["target_version", "rationale", "incident_category"]),
]


def system_prompt(scenario: str) -> str:
    title = SCENARIOS.get(scenario, {}).get("title", scenario)
    return f"""You are OpsPilot, an AI operations assistant built by Atlas Applied AI (a synthetic vendor) for \
Meridian Financial (a synthetic customer). You operate one synthetic production service, {SERVICE_KEY}. \
Everything is simulated; never claim to touch real systems. Demo scenario: {title}.

Rules:
1. Ground every statement in tool results from this conversation. Start by calling get_service_health. Never invent numbers.
2. If the service is degraded or critical, call read_logs (redacted; never include_raw) and get_deployment_history, \
then decide an incident_category: post_deploy_errors, capacity_pressure or unknown.
3. If the user names a specific action (restart, scale to N, roll back to a version), call exactly that tool with \
those arguments. Do not substitute a different action, and do not consult history first.
4. If the user asks you to fix or remediate without naming an action, first call query_remediation_history. If it \
returns supported=true, use its best remediation and cite its numbers. If its status is unavailable or failed, or \
supported=false, say "intelligence unavailable" (or "insufficient history"), use the low-risk restart_service and \
recommend escalation. Never claim a Keewano-informed recommendation in that case.
5. Never change anything for a status question. At most one state-changing action per turn.
6. Never decide on your own that an action needs approval or is forbidden. Calling the tool is what files the \
approval request with R2M, so always make the call and let R2M decide. If the tool returns approval_required, tell \
the user that a Meridian security reviewer must approve exactly that action in R2M, and that they should then say \
"continue". If it is denied, quote the reason codes; do not retry or work around a denial.
7. Reply in plain text with no markdown, under 120 words. After an action, give the verified before and after numbers."""

FAULT_NOTE = ("Fault-injection test requested by the vendor: this turn runs the faulty-1.0 build, whose "
              "rollback_deployment has lost its R2M gate. If the user asks you to run it, call get_service_health, then "
              "rollback_deployment with its exact previous_version (e.g. v2.0), then explain what the infrastructure "
              "and R2M did.")


class LiveWorkflow(Workflow):
    def __init__(self, *args: Any, chat: OpenAIChat, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.chat = chat
        self.acted = False
        self.svc_before: dict[str, Any] | None = None
        self.insight: Insight | None = None
        self.last_outcome: Outcome | None = None
        self.active_tools = self.tools
        self.open_ended = False  # "fix it" without a named action: history must inform the choice
        self.out.update(mode="live", model=chat.model, cost_label="estimated")

    def handle(self, message: str) -> dict[str, Any]:
        intent = parse_intent(message, self.scenario)
        pending = self.memory.peek(self._fingerprint())
        if intent.kind == "resume" and pending:
            return self._resume(message, pending)  # exact approved action; the model only narrates
        fault = self.scenario == "faulty" and self.can_fault_inject and self.fault_tools is not None
        return self._live(message, pending, fault=fault)

    # ---- the loop ------------------------------------------------------
    def _live(self, message: str, pending: dict[str, Any] | None, *, fault: bool = False) -> dict[str, Any]:
        safe_message = redact(message)
        self.open_ended = parse_intent(message, self.scenario).kind == "remediate"
        # Customers never get the faulty toolbox; for them the faulty scenario uses the normal, gated tools.
        self.active_tools = self.fault_tools if fault else self.tools
        with self.client.execution(self.scenario, metadata={"build_version": self.build.version, "intent": "live",
                                                            "model": self.chat.model}) as run:
            self._open(run)
            with self.step("RECEIVED", intent="live", model=self.chat.model):
                pass
            self.out["intent"] = "live"
            messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(self.scenario)},
                                              *self.memory.history(self.scenario, self._fingerprint()),
                                              {"role": "user", "content": safe_message}]
            if fault:
                messages.insert(1, {"role": "system", "content": FAULT_NOTE})
            if pending:
                messages.insert(1, {"role": "system", "content": f"Pending: {pending['tool']} awaits approval "
                                    f"{pending.get('approval_id')}. The user must say 'continue' after approval."})
            try:
                reply = self._loop(run, messages)
            except LiveModelError as exc:
                if not self.acted:
                    self.out["mode"] = "simulated-fallback"
                    note = f"(Live model unavailable: {exc}. Answered by deterministic OpsPilot.)"
                    return self._run_fresh(run, parse_intent(message, self.scenario), pending, [note])
                reply = f"{self.last_outcome.reply} (Live model unavailable after the action: {exc}.)"
            with self.step("REPORT"):
                pass
            self.out.update(reply=reply, state=self.state)
            self.memory.append_history(self.scenario, safe_message, redact(reply), self._fingerprint())
            return self.out

    def _loop(self, run: "ExecutionScope", messages: list[dict[str, Any]]) -> str:
        for _ in range(MAX_STEPS):
            msg = self.chat.complete(messages, TOOLS, tool_choice="none" if self.acted else "auto")
            calls = msg.get("tool_calls") or []
            if not calls:
                text = (msg.get("content") or "").strip()
                return text or (self.last_outcome.reply if self.last_outcome else "No answer from the live model.")
            messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": calls})
            for call in calls:
                result = self._dispatch(run, call)
                messages.append({"role": "tool", "tool_call_id": call.get("id"),
                                 "content": json.dumps(redact(result), default=str)[:6000]})
        return (self.last_outcome.reply if self.last_outcome else
                "I hit my step limit before reaching a conclusion; nothing was changed.")

    def _enter(self, state: str, **attrs: Any) -> None:
        if self.state != state:
            with self.step(state, **attrs):
                pass

    # ---- tool dispatch ------------------------------------------------
    def _dispatch(self, run: "ExecutionScope", call: dict[str, Any]) -> dict[str, Any]:
        name = (call.get("function") or {}).get("name", "")
        args = tool_arguments(call)
        if name in READ_TOOLS:
            self._enter("OBSERVE")
            try:
                if name == "get_service_health":
                    self.svc_before = self.tools.get_service_health()
                    self.out.setdefault("service_before", self.svc_before)
                    return self.svc_before
                if name == "get_deployment_history":
                    return self.tools.get_deployment_history()
                limit = max(1, min(int(args.get("limit") or 20), 200))
                return self.active_tools.read_logs(limit=limit, include_raw=bool(args.get("include_raw", False)))
            except PolicyDenied as exc:
                return {"error": "denied_by_r2m", "reasons": list(exc.reason_codes)}
            except (TypeError, ValueError):
                return {"error": "invalid_arguments"}
        if name == "query_remediation_history":
            self._enter("OPTIONAL_KEEWANO_HISTORY")
            category = args.get("incident_category") if args.get("incident_category") in CATEGORIES else "unknown"
            svc = self.svc_before or self.tools.get_service_health()
            self.insight = self._history(Diagnosis(category, "warning"), svc)
            return {**self.insight.as_dict(), "trust": "untrusted advisory data; R2M policy still decides"}
        if name in MUTATING:
            return self._act(run, name, args)
        return {"error": f"unknown tool {name}"}

    def _act(self, run: "ExecutionScope", name: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.acted:
            return {"error": "only one state-changing action per turn; report to the user instead"}
        if self.open_ended and self.insight is None and self.active_tools is not self.fault_tools:
            # Keewano is load-bearing for open-ended remediation: consult it before anything executes.
            category = args.get("incident_category") if args.get("incident_category") in CATEGORIES else "unknown"
            self._enter("OPTIONAL_KEEWANO_HISTORY", enforced=True)
            self.insight = self._history(Diagnosis(category, "warning"), self.svc_before or
                                         self.tools.get_service_health())
            return {"not_executed": True, "reason": "remediation history must be consulted first; reconsider your "
                    "action using it, then call the action tool again", **self.insight.as_dict()}
        self.acted = True
        svc = self.svc_before or self.tools.get_service_health()
        self.svc_before = svc
        category = args.get("incident_category")
        self.incident_category = category if category in CATEGORIES else diagnose(svc).category
        with self.step("DIAGNOSE", category=self.incident_category, deployment_version=svc["deployment_version"],
                       source="llm"):
            pass
        self.out["diagnosis"] = {"category": self.incident_category, "source": "llm"}
        if name == "rollback_deployment":
            arguments: dict[str, Any] = {"target_version": str(args.get("target_version") or svc.get("previous_version"))}
        elif name == "scale_instances":
            try:
                arguments = {"desired_replicas": int(args.get("desired_replicas"))}
            except (TypeError, ValueError):
                arguments = {"desired_replicas": 0}  # CAPACITY-001 denies it
        else:
            arguments = {}
        informed = bool(self.insight and self.insight.supported and self.insight.best
                        and self.insight.best.remediation == MUTATING[name])
        source = "fault_injection" if self.active_tools is self.fault_tools else ("keewano" if informed else "llm")
        proposal = Proposal(name, arguments, str(args.get("rationale") or "")[:300], source)
        with self.step("PROPOSE", tool=name, source=proposal.source):
            pass
        self.out["proposal"] = asdict(proposal)
        self._emit_insight(self.insight, proposal)
        outcome = self._execute(run, self.active_tools, proposal, svc)
        self.last_outcome = outcome
        return {"outcome": outcome.kind, **outcome.facts, "explanation": outcome.reply}

    # ---- resumed / fallback actions: the model narrates the real outcome ----
    def _gate_and_execute(self, run: "ExecutionScope", tools: Any, proposal: Proposal, svc_before: dict[str, Any],
                          *, notes: list[str], insight: Insight | None = None,
                          resume_id: str | None = None) -> dict[str, Any]:
        outcome = self._execute(run, tools, proposal, svc_before, resume_id=resume_id)
        facts = redact({"action": proposal.tool, "arguments": proposal.arguments, "outcome": outcome.kind,
                        **outcome.facts, "explanation": outcome.reply})
        try:
            msg = self.chat.complete([
                {"role": "system", "content": system_prompt(self.scenario)},
                *self.memory.history(self.scenario, self._fingerprint()),
                {"role": "user", "content": "Tell the user what just happened, using only these facts: "
                                            + json.dumps(facts, default=str)}], purpose="narrate_outcome")
            reply = (msg.get("content") or "").strip() or outcome.reply
        except LiveModelError:
            reply = outcome.reply
        out = self.finish(" ".join([reply, *notes]))
        self.memory.append_history(self.scenario, "continue", redact(out["reply"]), self._fingerprint())
        return out



class QuietLLM:
    """Template replies without a simulated model call, for the scripted paths in live mode."""

    def classify(self, message: str, scenario: str) -> Intent:
        return parse_intent(message, scenario)

    def summarize(self, purpose: str, facts: dict[str, Any], text: str) -> str:
        return text
