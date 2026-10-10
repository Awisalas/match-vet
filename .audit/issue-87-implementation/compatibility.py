"""Executable baseline compatibility checks for #87; no Store or network."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from matchvet.causal_trust import _PROFILE_DIGEST

BASE = "62b7a6a3e80ef87d9292c4df84225f540d9bceb3"
ROOT = Path(__file__).resolve().parents[2]


def before(path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{BASE}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def tree(raw: bytes) -> ast.Module:
    return ast.parse(raw)


def named(node: ast.Module, name: str) -> str:
    for value in node.body:
        if isinstance(value, (ast.FunctionDef, ast.ClassDef)) and value.name == name:
            return ast.dump(value)
        if isinstance(value, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in value.targets
        ):
            return ast.dump(value)
    raise AssertionError(name)


for path in sorted(ROOT.glob("src/matchvet/cb01*.py")):
    assert path.read_bytes() == before(str(path.relative_to(ROOT))), path
for path in (
    "src/matchvet/causal_witness.py",
    "src/matchvet/causal_transport.py",
    "src/matchvet/artifacts.py",
    "src/matchvet/matchweek_research.py",
    "src/matchvet/research_identity.py",
    "src/matchvet/research_capture.py",
):
    assert (ROOT / path).read_bytes() == before(path), path
path = "src/matchvet/causal_trust.py"
old, new = tree(before(path)), tree((ROOT / path).read_bytes())
for name in (
    "_PROFILE",
    "_FLOORS",
    "_authenticate",
    "_authenticate_checked",
    "_AuthenticatedTrust",
):
    assert named(old, name) == named(new, name), name
path = "src/matchvet/store.py"
old, new = tree(before(path)), tree((ROOT / path).read_bytes())
for name in ("Store", "StoreTransaction"):
    assert named(old, name) == named(new, name), name
old_owner = next(
    n for n in old.body if isinstance(n, ast.ClassDef) and n.name == "_ResearchOperation"
)
new_owner = next(
    n for n in new.body if isinstance(n, ast.ClassDef) and n.name == "_ResearchOperation"
)
for prior in old_owner.body:
    if isinstance(prior, ast.FunctionDef) and prior.name != "_authorize_insert":
        current = next(
            n for n in new_owner.body if isinstance(n, ast.FunctionDef) and n.name == prior.name
        )
        assert ast.dump(prior) == ast.dump(current), prior.name
assert _PROFILE_DIGEST == "7ba7e2f4db4de3aa7ef41d77d9ff5f8fafecb73c6de9c5b297924454f51e5c66"
print(
    "PASS: unchanged V1 profile, floors, TUF/interval semantics, CB01 bytes, "
    "schema and released readers"
)
