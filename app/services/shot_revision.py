"""Persistent prompt rewrite revisions for shot rows.

The workbench schema has no neutral JSON metadata column on ``shot_rows``.
Store prompt rewrite history beside project assets to avoid a migration while
keeping image/video/reference fields clean.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REVISION_SOURCE_DIRECTOR_PREFLIGHT = "director_preflight"
STORAGE = Path(__file__).resolve().parents[2] / "storage" / "projects"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_prompt_revision(
    *,
    shot_index: int,
    original_prompt: str,
    rewritten_prompt: str,
    source: str = REVISION_SOURCE_DIRECTOR_PREFLIGHT,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    return {
        "revision_id": uuid.uuid4().hex[:16],
        "shot_index": int(shot_index),
        "source": source,
        "original_prompt": original_prompt,
        "rewritten_prompt": rewritten_prompt,
        "created_at": timestamp,
        "applied_at": timestamp,
        "rolled_back_at": None,
        "preflight": preflight or {},
    }


def append_prompt_revision(project_id: str, revision: dict[str, Any]) -> dict[str, Any]:
    payload = _read_project_revisions(project_id)
    key = str(int(revision["shot_index"]))
    shots = payload.setdefault("shots", {})
    rows = shots.setdefault(key, [])
    rows.append(revision)
    _write_project_revisions(project_id, payload)
    return revision


def latest_prompt_revision(project_id: str, shot_index: int) -> dict[str, Any] | None:
    revisions = list_prompt_revisions(project_id, shot_index)
    if not revisions:
        return None
    active = [item for item in revisions if not item.get("rolled_back_at")]
    if not active:
        return None
    return active[-1]


def list_prompt_revisions(project_id: str, shot_index: int) -> list[dict[str, Any]]:
    payload = _read_project_revisions(project_id)
    rows = payload.get("shots", {}).get(str(int(shot_index)), [])
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


def mark_prompt_revision_rolled_back(
    project_id: str,
    shot_index: int,
    revision_id: str | None = None,
) -> dict[str, Any] | None:
    payload = _read_project_revisions(project_id)
    rows = payload.get("shots", {}).get(str(int(shot_index)), [])
    if not isinstance(rows, list):
        return None

    selected: dict[str, Any] | None = None
    for item in reversed(rows):
        if not isinstance(item, dict):
            continue
        if item.get("rolled_back_at"):
            continue
        if revision_id and item.get("revision_id") != revision_id:
            continue
        selected = item
        break
    if not selected:
        return None

    selected["rolled_back_at"] = now_iso()
    _write_project_revisions(project_id, payload)
    return selected


def revision_public_payload(project_id: str, shot_index: int) -> dict[str, Any]:
    revisions = list_prompt_revisions(project_id, shot_index)
    return {
        "latest": latest_prompt_revision(project_id, shot_index),
        "items": revisions,
        "count": len(revisions),
    }


def _project_revision_path(project_id: str) -> Path:
    safe_project_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(project_id)).strip("._")
    if not safe_project_id:
        safe_project_id = "unknown_project"
    base = (STORAGE / safe_project_id).resolve()
    base.relative_to(STORAGE.resolve())
    base.mkdir(parents=True, exist_ok=True)
    return base / "shot_prompt_revisions.json"


def _read_project_revisions(project_id: str) -> dict[str, Any]:
    path = _project_revision_path(project_id)
    if not path.exists():
        return {"version": 1, "shots": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "shots": {}}
    if not isinstance(data, dict):
        return {"version": 1, "shots": {}}
    if not isinstance(data.get("shots"), dict):
        data["shots"] = {}
    data.setdefault("version", 1)
    return data


def _write_project_revisions(project_id: str, payload: dict[str, Any]) -> None:
    path = _project_revision_path(project_id)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
