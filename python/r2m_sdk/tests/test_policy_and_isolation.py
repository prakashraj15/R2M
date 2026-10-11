import ast
import importlib.util
from pathlib import Path

import pytest

from r2m import compute_artifact_hash, policy

SRC = Path(__file__).parents[1] / "src" / "r2m"

POLICY_SRC = '''
from r2m import PolicyResult, policy

@policy(id="P-1", version="1.0.0", description="d", tools=["t"])
def p(ctx):
    return PolicyResult.allow({reason!r})
'''


def _load(tmp_path: Path, name: str, reason: str, newline: str = "\n"):
    f = tmp_path / f"{name}.py"
    f.write_bytes(POLICY_SRC.format(reason=reason).replace("\n", newline).encode())
    spec = importlib.util.spec_from_file_location(name, f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.p


def test_hash_is_reproducible_and_line_ending_independent(tmp_path):
    a = _load(tmp_path, "a", "OK")
    b = _load(tmp_path, "b", "OK", newline="\r\n")
    assert a.artifact_hash == b.artifact_hash
    assert a.artifact_hash.startswith("sha256:")


def test_source_change_changes_hash(tmp_path):
    assert _load(tmp_path, "a", "OK").artifact_hash != _load(tmp_path, "b", "CHANGED").artifact_hash


def test_metadata_change_changes_hash():
    assert compute_artifact_hash(b"x", {"version": "1.0.0"}) != compute_artifact_hash(b"x", {"version": "1.0.1"})


def test_semver_enforced():
    with pytest.raises(ValueError):
        policy(id="X", version="v1", description="d", tools=["t"])


def test_sdk_does_not_import_platform_or_agent():
    forbidden = ("r2m_platform", "mock_agent", "db", "asyncpg")
    for f in SRC.glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for n in names:
                assert n.split(".")[0] not in forbidden, f"{f.name} imports {n}"
