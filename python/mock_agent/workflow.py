"""OpsPilot's deterministic state machine (spec §7.2):

RECEIVED -> OBSERVE -> DIAGNOSE -> (OPTIONAL_KEEWANO_HISTORY) -> PROPOSE -> POLICY_GATE
         -> (WAIT_APPROVAL | DENIED | EXECUTE) -> VERIFY -> REPORT

Every transition emits a ``state.transition`` event and an orchestrator span. The policy gate and
the execution happen inside one guarded tool call (the SDK path), so EXECUTE records the outcome
of the call made under POLICY_GATE.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Iterator

from r2m import ApprovalRequired, EventKind, PolicyDenied, Severity, resume_action

from . import insights as insights_mod
from .llm import Intent, SimulatedLLM, parse_intent
from .build import FAULTY_VERSION
from .scenarios import suggestions
from .service_state import SERVICE_KEY, Diagnosis, diagnose
from .tools import InfrastructureRefused, Toolbox

if TYPE_CHECKING:
    from r2m import ExecutionScope, R2MClient

    from .build import Build
    from .memory import ConversationMemory

ORCHESTRATOR = "orchestrator"


@dataclass
class Proposal:
    tool: str | None
    arguments: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    source: str = "none"  # user | keewano | deterministic | fault_injection | none


@dataclass
class Outcome:
    kind: str  # approval_required | denied | refused | executed
    reply: str  # deterministic reply text
    facts: dict[str, Any] = field(default_factory=dict)  # what a live model is told


class Workflow:
    def __init__(self, client: "R2MClient", tools: Toolbox, llm: SimulatedLLM, memory: "ConversationMemory",
                 insights: Any, *, scenario: str, build: "Build", deployment_status: str,
                 can_fault_inject: bool, fault_tools: Toolbox | None = None):
        self.client = client
        self.tools = tools
        self.fault_tools = fault_tools
        self.llm = llm
        self.memory = memory
        self.insights = insights
        self.scenario = scenario
        self.build = build
        self.deployment_status = deployment_status
        self.can_fault_inject = can_fault_inject
        self.state: str | None = None
        self.incident_category: str | None = None
        self.out: dict[str, Any] = {
            "scenario": scenario, "steps": [], "decision": None, "reasons": [], "action_id": None,
            "approval_id": None, "proposal": None, "insight": None,
            "build": {"version": build.version, "deployment_status": deployment_status},
            "cost_label": "simulated", "suggestions": suggestions(scenario),
        }

    # ---- plumbing ------------------------------------------------------
    @contextmanager
    def step(self, state: str, **attrs: Any) -> Iterator[Any]:
        self.client.transition(self.state, state, **attrs)
        self.state = state
        self.out["steps"].append(state)
        with self.client.span(f"step:{state}", component=ORCHESTRATOR, attributes=attrs) as span:
            yield span

    def finish(self, reply: str, facts: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.step("REPORT"):
            self.out["reply"] = self.llm.summarize("compose_reply", facts or {}, reply)
        self.out["state"] = self.state
        return self.out

    # ---- entry ---------------------------------------------------------
    def handle(self, message: str) -> dict[str, Any]:
        intent = parse_intent(message, self.scenario)
        pending = self.memory.peek()
        if intent.kind == "resume" and pending:
            return self._resume(message, pending)
        return self._fresh(message, intent, pending)

    def _open(self, run: "ExecutionScope") -> None:
        self.out.update(execution_id=run.execution_id, trace_id=run.trace_id)

    # ---- fresh request -------------------------------------------------
    def _fresh(self, message: str, intent: Intent, pending: dict[str, Any] | None) -> dict[str, Any]:
        with self.client.execution(self.scenario, metadata={"build_version": self.build.version,
                                                            "intent": intent.kind}) as run:
            self._open(run)
            with self.step("RECEIVED", intent=intent.kind, explicit=intent.explicit):
                self.llm.classify(message, self.scenario)
            return self._run_fresh(run, intent, pending)

    def _run_fresh(self, run: "ExecutionScope", intent: Intent, pending: dict[str, Any] | None,
                   notes: list[str] | None = None) -> dict[str, Any]:
        """Deterministic path from OBSERVE onwards, inside an already open execution."""
        self.out["intent"] = intent.kind
        if intent.kind == "resume":
            return self.finish("There is no action waiting for approval. Ask me to check or fix payments-api.")
        notes = list(notes or [])
        if pending:
            notes.append(f"Note: {pending['proposal']['tool']} is still waiting for approval "
                         f"{pending.get('approval_id')}; say 'continue' once it is approved.")
        if intent.kind == "fault_injection" and not (self.can_fault_inject and self.fault_tools):
            notes.append("Fault injection is a vendor-only test path and is not available to this role; "
                         "observing only.")
            intent = Intent("observe", explicit=False)

        with self.step("OBSERVE"):
            svc = self.tools.get_service_health()
            self.tools.get_deployment_history()
            logs = self._read_logs(svc, intent, notes)
        self.out["service_before"] = svc

        with self.step("DIAGNOSE") as span:
            dx = diagnose(svc, logs)
            span.set_attributes(category=dx.category, severity=dx.severity,
                                deployment_version=svc["deployment_version"])
            self.llm.summarize("diagnose", {"service": svc, "logs": logs}, f"{dx.category}: {'; '.join(dx.evidence)}")
        self.out["diagnosis"] = asdict(dx)
        self.incident_category = dx.category

        if intent.kind == "observe" or (intent.kind == "remediate" and not dx.needs_action):
            return self.finish(" ".join([_status_line(svc, dx), *notes]), {"service": svc})

        insight = None
        if intent.kind == "remediate":
            with self.step("OPTIONAL_KEEWANO_HISTORY"):
                insight = self._history(dx, svc)

        with self.step("PROPOSE") as span:
            proposal = self._propose(intent, dx, svc, insight)
            span.set_attributes(tool=proposal.tool, source=proposal.source)
        self.out["proposal"] = asdict(proposal)
        if proposal.tool is None:
            return self.finish(" ".join([_status_line(svc, dx), proposal.rationale, *notes]))

        tools = self.fault_tools if proposal.source == "fault_injection" else self.tools
        return self._gate_and_execute(run, tools, proposal, svc, notes=notes, insight=insight)

    def _read_logs(self, svc: dict[str, Any], intent: Intent, notes: list[str]) -> list[str] | None:
        if svc["health_status"] == "healthy" and intent.kind == "observe":
            return None
        try:
            return self.tools.read_logs(limit=20)["lines"]
        except PolicyDenied as exc:
            notes.append(f"Logs unavailable: R2M denied read_logs ({', '.join(exc.reason_codes)}).")
            return None

    # ---- Keewano -------------------------------------------------------
    def _history(self, dx: Diagnosis, svc: dict[str, Any]) -> insights_mod.Insight:
        question = (f"For incidents of category {dx.category} on {SERVICE_KEY} after deployment "
                    f"{svc['deployment_version']}, which remediation (restart, rollback, scale) was most often "
                    f"followed by recovery? Give samples and successes per remediation.")
        with self.client.span("keewano.query", component=ORCHESTRATOR) as span:
            if self.insights is None:
                response = {"status": "unavailable"}
            else:
                try:
                    response = self.insights.query(question)
                except Exception as exc:  # advisory only: any failure means "unavailable"
                    response = {"status": "failed", "error_class": type(exc).__name__}
            insight = insights_mod.interpret(response)
            span.set_attributes(status=insight.status, sample_count=insight.sample_count, supported=insight.supported)
        self.out["insight"] = insight.as_dict()
        return insight

    def _emit_insight(self, insight: insights_mod.Insight | None, proposal: Proposal) -> None:
        if insight is None:
            return
        self.client.event(EventKind.INSIGHT, "keewano.remediation_history", {
            **insight.as_dict(), "proposed_action": proposal.tool, "proposal_source": proposal.source,
            "keewano_informed": proposal.source == "keewano"})

    # ---- proposal ------------------------------------------------------
    def _propose(self, intent: Intent, dx: Diagnosis, svc: dict[str, Any],
                 insight: insights_mod.Insight | None) -> Proposal:
        prev, replicas = svc.get("previous_version"), int(svc["replicas"])
        if intent.kind in ("rollback", "fault_injection"):
            target = intent.params.get("target_version") or prev
            source = "fault_injection" if intent.kind == "fault_injection" else "user"
            return Proposal("rollback_deployment", {"target_version": target},
                            f"Roll back {SERVICE_KEY} from {svc['deployment_version']} to {target}.", source)
        if intent.kind == "scale":
            n = int(intent.params.get("desired_replicas") or replicas + 2)
            return Proposal("scale_instances", {"desired_replicas": n}, f"Scale {SERVICE_KEY} to {n} replicas.", "user")
        if intent.kind == "restart":
            return Proposal("restart_service", {}, f"Restart {SERVICE_KEY}.", "user")

        # remediate
        if insight is not None and insight.supported and insight.best is not None:
            proposal = _from_remediation(insight.best.remediation, svc, insight.label, "keewano")
        elif dx.category == "post_deploy_errors":
            reason = insight.label if insight else insights_mod.UNAVAILABLE_LABEL
            proposal = Proposal("restart_service", {},
                                f"No Keewano-informed recommendation ({reason}), so I took the safe deterministic "
                                f"step: a low-risk restart, escalating to a human if errors persist.", "deterministic")
        elif dx.category == "capacity_pressure":
            proposal = Proposal("scale_instances", {"desired_replicas": min(replicas + 1, 4)},
                                "CPU saturation: add one replica within the no-approval limit.", "deterministic")
        else:
            proposal = Proposal(None, {}, "Cause unclear; escalating to a human operator without changes.", "none")
        self._emit_insight(insight, proposal)
        return proposal

    # ---- gate / execute / verify --------------------------------------
    def _execute(self, run: "ExecutionScope", tools: Toolbox, proposal: Proposal, svc_before: dict[str, Any],
                 *, resume_id: str | None = None) -> Outcome:
        """POLICY_GATE -> (WAIT_APPROVAL | DENIED | EXECUTE -> VERIFY). Returns what happened; never replies."""
        fn = tools.by_name(proposal.tool)
        try:
            with self.step("POLICY_GATE", tool=proposal.tool, arguments=proposal.arguments, resumed=bool(resume_id)):
                if resume_id:
                    with resume_action(resume_id):
                        result = fn(**proposal.arguments)
                else:
                    result = fn(**proposal.arguments)
        except ApprovalRequired as exc:
            self.out.update(decision="REQUIRE_APPROVAL", reasons=list(exc.reason_codes), action_id=exc.action_id,
                            approval_id=exc.approval_id)
            with self.step("WAIT_APPROVAL", action_id=exc.action_id, approval_id=exc.approval_id):
                self.memory.save_pending({"action_id": exc.action_id, "approval_id": exc.approval_id,
                                          "execution_id": run.execution_id, "trace_id": run.trace_id,
                                          "tool": proposal.tool, "proposal": asdict(proposal),
                                          "incident_category": self.incident_category})
            run.suspend()
            return Outcome("approval_required", " ".join([
                f"{proposal.rationale} R2M requires approval ({', '.join(exc.reason_codes)}).",
                f"Approval request {exc.approval_id} is waiting for Meridian security review in R2M; it covers "
                f"exactly this action. Once it is approved, say 'continue'."]),
                {"decision": "REQUIRE_APPROVAL", "reasons": list(exc.reason_codes), "approval_id": exc.approval_id})
        except PolicyDenied as exc:
            if resume_id:
                self.memory.clear_pending()
            self.out.update(decision="DENY", reasons=list(exc.reason_codes), action_id=exc.action_id)
            with self.step("DENIED", reasons=list(exc.reason_codes)):
                pass
            return Outcome("denied", " ".join([f"R2M denied {proposal.tool}: {', '.join(exc.reason_codes)}. "
                                               f"Nothing was changed.", self._deny_hint(exc.reason_codes)]).strip(),
                           {"decision": "DENY", "reasons": list(exc.reason_codes), "changed": False})
        except InfrastructureRefused as exc:
            self.out.update(decision="DENY", reasons=["INFRASTRUCTURE_REFUSED_NO_GRANT"],
                            incident_id=exc.result.get("incident_id"), infrastructure=exc.result)
            with self.step("DENIED", reasons=["INFRASTRUCTURE_REFUSED_NO_GRANT"],
                           incident_id=exc.result.get("incident_id"), fault_injection=proposal.source == "fault_injection"):
                self.client.event(EventKind.ERROR, "unguarded_mutation_refused", {
                    "tool": proposal.tool, "incident_id": exc.result.get("incident_id"),
                    "build_version": self.build.version}, severity=Severity.CRITICAL, status="refused")
            return Outcome("refused",
                           f"Fault injection ({FAULTY_VERSION} code path): {proposal.tool} ran without its R2M gate. The "
                           f"simulated infrastructure refused it because there was no grant, and R2M opened critical "
                           f"incident {exc.result.get('incident_id')}. This is why the faulty build fails mandatory "
                           f"regression and cannot be released.",
                           {"decision": "DENY", "reasons": ["INFRASTRUCTURE_REFUSED_NO_GRANT"], "changed": False})

        if resume_id:
            self.memory.clear_pending()
        action_id = result.get("action_id")
        self.out.update(decision="ALLOW", reasons=["ALLOWED"], action_id=action_id)
        with self.step("EXECUTE", action_id=action_id, tool=proposal.tool):
            pass
        with self.step("VERIFY", action_id=action_id) as span:
            after = self.tools.get_service_health()
            ok, summary = _verify(proposal, svc_before, after)
            span.set_attributes(verified=ok, tool=proposal.tool, recovered=after["health_status"] == "healthy",
                                category=self.incident_category, deployment_version=svc_before["deployment_version"],
                                recommendation_source=proposal.source)
            self.client.report_verification(action_id, verified=ok, details={"summary": summary, "after": after})
        self.out.update(service_after=after, verified=ok)
        tail = []
        if proposal.tool == "restart_service" and after["health_status"] != "healthy":
            tail.append("Still degraded: the fault looks code-related. Escalating; a rollback (needs approval) "
                        "is the likely fix.")
        reply = " ".join([f"Done: {_done_phrase(proposal)}.", proposal.rationale if proposal.source not in ("user", "llm")
                          else "", f"Verified: {summary}.", *tail]).replace("  ", " ")
        return Outcome("executed", reply, {"decision": "ALLOW", "verified": ok, "service_after": after,
                                           "summary": summary})

    def _gate_and_execute(self, run: "ExecutionScope", tools: Toolbox, proposal: Proposal, svc_before: dict[str, Any],
                          *, notes: list[str], insight: insights_mod.Insight | None = None,
                          resume_id: str | None = None) -> dict[str, Any]:
        outcome = self._execute(run, tools, proposal, svc_before, resume_id=resume_id)
        return self.finish(" ".join([outcome.reply, *notes]))

    def _deny_hint(self, codes: tuple[str, ...]) -> str:
        if "DEPLOYMENT_NOT_ACTIVE" in codes:
            return (f"Build {self.build.version} has not been released to this installation yet "
                    f"(status {self.deployment_status}). Run evals and have the release manager deploy it.")
        if any(c.startswith("POLICY_NOT_APPROVED") for c in codes):
            return "The policy revision this tool needs is not approved for this installation."
        if any(c.startswith("APPROVAL_") for c in codes):
            return "That approval can't be used any more. Ask again to request a new one."
        return ""

    # ---- resume --------------------------------------------------------
    def _resume(self, message: str, pending: dict[str, Any]) -> dict[str, Any]:
        with self.client.execution(self.scenario, execution_id=pending["execution_id"], resume=True,
                                   metadata={"build_version": self.build.version, "intent": "resume"}) as run:
            self._open(run)
            with self.step("RECEIVED", intent="resume", action_id=pending["action_id"]):
                self.llm.classify(message, self.scenario)
            self.out["intent"] = "resume"
            pending = self.memory.pending() or pending  # traced read on the memory node
            p = pending["proposal"]
            proposal = Proposal(p["tool"], p["arguments"], p["rationale"], p["source"])
            self.incident_category = pending.get("incident_category")
            self.out["proposal"] = asdict(proposal)
            svc = self.tools.get_service_health()
            self.out["service_before"] = svc
            return self._gate_and_execute(run, self.tools, proposal, svc, notes=[], resume_id=pending["action_id"])


def _from_remediation(remediation: str, svc: dict[str, Any], label: str, source: str) -> Proposal:
    if remediation == "rollback":
        return Proposal("rollback_deployment", {"target_version": svc.get("previous_version")},
                        f"{label}. Proposing rollback to {svc.get('previous_version')}.", source)
    if remediation == "scale":
        n = int(svc["replicas"]) + 2
        return Proposal("scale_instances", {"desired_replicas": n}, f"{label}. Proposing scale to {n} replicas.", source)
    return Proposal("restart_service", {}, f"{label}. Proposing restart.", source)


def _done_phrase(proposal: Proposal) -> str:
    if proposal.tool == "rollback_deployment":
        return f"rolled {SERVICE_KEY} back to {proposal.arguments['target_version']}"
    if proposal.tool == "scale_instances":
        return f"scaled {SERVICE_KEY} to {proposal.arguments['desired_replicas']} replicas"
    return f"restarted {SERVICE_KEY}"


def _verify(proposal: Proposal, before: dict[str, Any], after: dict[str, Any]) -> tuple[bool, str]:
    change = (f"error rate {before['error_rate_pct']}% -> {after['error_rate_pct']}%, "
              f"health {before['health_status']} -> {after['health_status']}")
    if proposal.tool == "rollback_deployment":
        ok = after["deployment_version"] == proposal.arguments["target_version"] and after["health_status"] == "healthy"
        return ok, f"now on {after['deployment_version']}, {change}"
    if proposal.tool == "scale_instances":
        ok = int(after["replicas"]) == int(proposal.arguments["desired_replicas"])
        return ok, f"replicas {before['replicas']} -> {after['replicas']}, {change}"
    return after["error_rate_pct"] <= before["error_rate_pct"], change


def _status_line(svc: dict[str, Any], dx: Diagnosis) -> str:
    line = (f"{SERVICE_KEY} is {svc['health_status']} on {svc['deployment_version']}: error rate "
            f"{svc['error_rate_pct']}%, p95 {svc['p95_latency_ms']} ms, {svc['replicas']} replicas.")
    if dx.needs_action:
        line += f" Diagnosis: {dx.category.replace('_', ' ')} ({'; '.join(dx.evidence)}). Say 'fix it' for a proposal."
    else:
        line += " No action taken."
    return line
