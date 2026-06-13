from __future__ import annotations

from typing import Any


def require(condition: bool, message: str, evidence: Any = None) -> None:
    if not condition:
        detail = "" if evidence is None else f": {evidence!r}"
        raise AssertionError(f"{message}{detail}")
