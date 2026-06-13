from __future__ import annotations

import ast
from pathlib import Path


ALEMBIC_VERSION_NUM_LIMIT = 32


def _literal_assignment(module: ast.Module, name: str) -> str | None:
    for node in module.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    return None


def test_alembic_revision_ids_fit_default_version_table() -> None:
    versions_dir = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    too_long: list[tuple[str, str, int]] = []

    for path in sorted(versions_dir.glob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"))
        revision = _literal_assignment(module, "revision")
        if revision and len(revision) > ALEMBIC_VERSION_NUM_LIMIT:
            too_long.append((path.name, revision, len(revision)))

    assert not too_long
