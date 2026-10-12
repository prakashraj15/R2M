"""Build identity and topology. Evals, release gate and runtime all use the same artifact digest.

The source digest is SHA-256 over the agent's own source files (tests excluded, line endings
normalised), so changing agent code yields a new build that must pass evals and be released
again. The faulty variant exists only for fault-injection evals and is never registered at runtime.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
AGENT_SLUG = "opspilot"
AGENT_NAME = "OpsPilot"
AGENT_DESCRIPTION = "AI operations assistant for the synthetic payments-api service (demo)."
SAFE_VERSION = "safe-1.0"
FAULTY_VERSION = "faulty-1.0"


@dataclass(frozen=True)
class Build:
    version: str
    variant: str  # "safe" | "faulty"
    source_digest: str
    artifact_digest: str

    @property
    def fault_injection(self) -> bool:
        return self.variant == "faulty"

    def register_kwargs(self) -> dict[str, str]:
        return {"build_version": self.version, "source_digest": self.source_digest,
                "artifact_digest": self.artifact_digest}

    def eval_payload(self) -> dict[str, str]:
        return {"version": self.version, "source_digest": self.source_digest, "artifact_digest": self.artifact_digest}


@lru_cache(maxsize=1)
def source_digest() -> str:
    h = hashlib.sha256()
    files = sorted(p for p in PACKAGE_DIR.rglob("*.py")
                   if "tests" not in p.relative_to(PACKAGE_DIR).parts and "__pycache__" not in p.parts)
    for f in files:
        h.update(f.relative_to(PACKAGE_DIR).as_posix().encode() + b"\0")
        h.update(f.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return "sha256:" + h.hexdigest()


def build(version: str = SAFE_VERSION) -> Build:
    """`safe-<n>` or `faulty-<n>` (e.g. safe-1.1). A new version is a new artifact that must pass evals and release."""
    m = re.fullmatch(r"(safe|faulty)-\d+(?:\.\d+)*", version)
    if not m:
        raise ValueError(f"unknown OpsPilot build {version!r}; expected safe-<n> or faulty-<n>, e.g. {SAFE_VERSION}")
    src = source_digest()
    artifact = "sha256:" + hashlib.sha256(f"{src}:{version}:{m.group(1)}".encode()).hexdigest()
    return Build(version, m.group(1), src, artifact)


TOOLS = ("get_service_health", "read_logs", "get_deployment_history", "restart_service", "scale_instances",
         "rollback_deployment")

# Keys match scripts/seed_demo.py so registration upserts the seeded topology rather than duplicating it.
COMPONENTS = [
    {"component_key": "orchestrator", "kind": "orchestrator", "label": "OpsPilot orchestrator"},
    {"component_key": "sim-llm", "kind": "model", "label": "Simulated LLM (no vendor)",
     "metadata": {"model": "opspilot-sim-1", "cost_source": "simulated"}},
    {"component_key": "openai-llm", "kind": "model", "label": "OpenAI model (live mode, optional)",
     "metadata": {"provider": "openai", "cost_source": "estimated"}},
    {"component_key": "conversation-memory", "kind": "memory", "label": "Conversation memory"},
    {"component_key": "r2m-postgres", "kind": "storage", "label": "R2M Postgres (Aiven)"},
    {"component_key": "container", "kind": "compute", "label": "R2M container"},
    {"component_key": "policy-gateway", "kind": "gateway", "label": "R2M SDK policy gateway"},
    *({"component_key": t, "kind": "tool", "label": t} for t in TOOLS),
]
EDGES = [
    {"source": "orchestrator", "target": "sim-llm", "edge_kind": "calls"},
    {"source": "orchestrator", "target": "openai-llm", "edge_kind": "calls"},
    {"source": "orchestrator", "target": "conversation-memory", "edge_kind": "reads"},
    {"source": "conversation-memory", "target": "r2m-postgres", "edge_kind": "stores"},
    {"source": "orchestrator", "target": "container", "edge_kind": "runs_on"},
    {"source": "orchestrator", "target": "policy-gateway", "edge_kind": "calls"},
    *({"source": "policy-gateway", "target": t, "edge_kind": "guards"} for t in TOOLS),
]
