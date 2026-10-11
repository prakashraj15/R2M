"""Code-owned policies with reproducible artifact hashes (spec §6).

A policy is a Python function plus static metadata. Its artifact hash is SHA-256 over
the canonical metadata and the normalised source bytes of the module that defines
it, so editing the policy file (or any helper in it) yields a new hash that needs
fresh customer approval. We never hash ``repr(fn)`` or other unstable introspection.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .types import Decision

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.\-]+)?$")


@dataclass(frozen=True)
class PolicyContext:
    tool: str
    arguments: dict[str, Any]
    environment: str
    customer_org_id: str
    execution_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason_code: str
    message: str = ""

    @classmethod
    def allow(cls, reason_code: str = "ALLOWED", message: str = "") -> "PolicyResult":
        return cls(Decision.ALLOW, reason_code, message)

    @classmethod
    def deny(cls, reason_code: str, message: str = "") -> "PolicyResult":
        return cls(Decision.DENY, reason_code, message)

    @classmethod
    def require_approval(cls, reason_code: str, message: str = "") -> "PolicyResult":
        return cls(Decision.REQUIRE_APPROVAL, reason_code, message)


PolicyFn = Callable[[PolicyContext], PolicyResult]


def _normalise_source(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def compute_artifact_hash(source: bytes, metadata: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode())
    h.update(b"\n")
    h.update(_normalise_source(source))
    return "sha256:" + h.hexdigest()


@dataclass(frozen=True)
class Policy:
    id: str
    version: str
    description: str
    enforcement_point: str
    scope: str
    owner: str
    tools: tuple[str, ...]
    fn: PolicyFn = field(repr=False, compare=False)
    source_file: str = field(repr=False, compare=False, default="")
    artifact_hash: str = ""

    def static_metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "description": self.description,
            "enforcement_point": self.enforcement_point,
            "scope": self.scope,
            "owner": self.owner,
            "tools": sorted(self.tools),
        }

    def manifest(self) -> dict[str, Any]:
        return {**self.static_metadata(), "artifact_hash": self.artifact_hash,
                "source_file": Path(self.source_file).name}

    def evaluate(self, ctx: PolicyContext) -> PolicyResult:
        try:
            result = self.fn(ctx)
        except Exception as exc:  # a crashing policy must never allow
            return PolicyResult.deny("POLICY_EVALUATION_ERROR", type(exc).__name__)
        if not isinstance(result, PolicyResult):
            return PolicyResult.deny("POLICY_INVALID_RESULT")
        return result


def policy(
    *,
    id: str,
    version: str,
    description: str,
    tools: tuple[str, ...] | list[str],
    scope: str = "production",
    owner: str = "",
    enforcement_point: str = "tool.pre_execute",
) -> Callable[[PolicyFn], Policy]:
    """Declare a code-owned policy. The decorated function becomes a :class:`Policy`."""
    if not _SEMVER.match(version):
        raise ValueError(f"policy {id}: version must be semver, got {version!r}")
    if not tools:
        raise ValueError(f"policy {id}: at least one tool must be listed")

    def wrap(fn: PolicyFn) -> Policy:
        source_file = inspect.getsourcefile(fn) or ""
        source = Path(source_file).read_bytes() if source_file else b""
        p = Policy(id=id, version=version, description=description, enforcement_point=enforcement_point,
                   scope=scope, owner=owner, tools=tuple(tools), fn=fn, source_file=source_file)
        object.__setattr__(p, "artifact_hash", compute_artifact_hash(source, p.static_metadata()))
        return p

    return wrap
