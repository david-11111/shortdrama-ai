from __future__ import annotations

import ast
from pathlib import Path


def test_public_ltx_smoke_requires_explicit_reference_image() -> None:
    source = Path("scripts/smoke_ltx_public_provider.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

    assert "make_png" not in function_names
    assert "--image" in source
    assert "required=True" in source
    assert 'provider="ltx2.3"' in source
