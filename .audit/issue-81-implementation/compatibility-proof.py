"""Read-only baseline proof; never opens a store or contacts a witness service."""

import ast
import subprocess
from pathlib import Path

base = Path(__file__).with_name("base.txt").read_text().strip()


def original(path: Path) -> bytes:
    return subprocess.check_output(["git", "show", f"{base}:{path}"])


unchanged = (
    Path("src/matchvet/artifacts.py"),
    Path("src/matchvet/research_identity.py"),
    *Path("src/matchvet").glob("cb01*.py"),
)
for path in unchanged:
    assert path.read_bytes() == original(path), path
print(f"PASS: {len(unchanged)} generic artifact/identity/CB01 files are byte-identical")


def tree(path: Path, *, baseline: bool) -> ast.Module:
    return ast.parse(original(path) if baseline else path.read_bytes())


def named(nodes: list[ast.stmt], name: str) -> ast.AST:
    return next(node for node in nodes if getattr(node, "name", None) == name)


path = Path("src/matchvet/matchweek_research.py")
prior, current = tree(path, baseline=True), tree(path, baseline=False)
for name in ("_Graph", "_version", "_reference", "FrozenMatchweekResearch"):
    assert ast.dump(named(prior.body, name)) == ast.dump(named(current.body, name)), name
before = named(prior.body, "MatchweekResearchRepository")
after = named(current.body, "MatchweekResearchRepository")
assert isinstance(before, ast.ClassDef) and isinstance(after, ast.ClassDef)
for name in ("_admit", "_manifest", "_validate_manifest", "seal_completed"):
    assert ast.dump(named(before.body, name)) == ast.dump(named(after.body, name)), name
print(
    "PASS: original v1 graph, identities, admission, canonical manifest and sealing are identical"
)

path = Path("src/matchvet/store.py")


def migrations(parsed: ast.Module) -> ast.Assign:
    return next(
        node
        for node in parsed.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "MIGRATIONS" for target in node.targets
        )
    )


assert ast.dump(migrations(tree(path, baseline=True))) == ast.dump(
    migrations(tree(path, baseline=False))
)
print("PASS: generic SQLite migrations/schema are identical; no migration")
