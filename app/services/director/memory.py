from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import safe_path_segment
from .store import (
    fetch_character_rows,
    fetch_project_profile_row,
    fetch_rework_rows,
    insert_rework_row,
    upsert_character_row,
    upsert_project_profile_row,
)


ROOT_DIR = Path(__file__).resolve().parents[3]
PROJECTS_DIR = ROOT_DIR / "storage" / "projects"
MEMORY_DIRNAME = "director_memory"
PROJECT_PROFILE_FILE = "project_profile.json"
CHARACTER_PROFILE_FILE = "character_profiles.json"
REWORK_HISTORY_FILE = "rework_history.jsonl"

PROJECT_LOCKABLE_FIELDS = {
    "title", "genre", "theme", "style", "tone", "visual_style", "pace", "audience", "do_not_change"
}
CHARACTER_LOCKABLE_FIELDS = {
    "name", "role", "persona", "traits", "relationship", "signature_lines", "visual_tags", "do_not_change"
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _memory_root(project_id: str) -> Path:
    return PROJECTS_DIR / safe_path_segment(project_id, default="project") / MEMORY_DIRNAME


def _profile_path(project_id: str) -> Path:
    return _memory_root(project_id) / PROJECT_PROFILE_FILE


def _character_path(project_id: str) -> Path:
    return _memory_root(project_id) / CHARACTER_PROFILE_FILE


def _rework_path(project_id: str) -> Path:
    return _memory_root(project_id) / REWORK_HISTORY_FILE


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _loads_json(text: str | None, default: Any) -> Any:
    try:
        if text is None or text == "":
            return default
        return json.loads(text)
    except Exception:
        return default


def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
    _ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")


def _merge_locked(existing: dict[str, Any], incoming: dict[str, Any], lockable_fields: set[str], force: bool = False) -> dict[str, Any]:
    existing = dict(existing or {})
    incoming = dict(incoming or {})
    locked_fields = set(existing.get("locked_fields", []))
    merged = dict(existing)
    for key, value in incoming.items():
        if key == "locked_fields":
            continue
        if key in lockable_fields and key in locked_fields and not force:
            continue
        merged[key] = value
    incoming_locked = incoming.get("locked_fields", [])
    merged["locked_fields"] = sorted(locked_fields.union({str(item).strip() for item in incoming_locked if str(item).strip()}))
    merged["updated_at"] = _utc_now_iso()
    if "created_at" not in merged:
        merged["created_at"] = _utc_now_iso()
    return merged


def get_project_memory(project_id: str) -> dict[str, Any]:
    project_row = fetch_project_profile_row(project_id)
    character_rows = fetch_character_rows(project_id)
    rework_rows = fetch_rework_rows(project_id, limit=20)

    project_profile = {
        "project_id": str(project_id or "").strip(),
        "profile": _loads_json(project_row.get("profile_json"), {}) if project_row else {},
        "locked_fields": _loads_json(project_row.get("locked_fields_json"), []) if project_row else [],
        "created_at": project_row.get("created_at", _utc_now_iso()) if project_row else _utc_now_iso(),
        "updated_at": project_row.get("updated_at", _utc_now_iso()) if project_row else _utc_now_iso(),
    }

    characters: dict[str, Any] = {}
    updated_at = _utc_now_iso()
    for row in character_rows:
        profile = _loads_json(row.get("profile_json"), {})
        profile["name"] = str(row.get("character_name", "")).strip()
        profile["locked_fields"] = _loads_json(row.get("locked_fields_json"), [])
        profile["created_at"] = row.get("created_at", _utc_now_iso())
        profile["updated_at"] = row.get("updated_at", _utc_now_iso())
        characters[profile["name"]] = profile
        updated_at = row.get("updated_at", updated_at) or updated_at

    character_profiles = {
        "project_id": str(project_id or "").strip(),
        "characters": characters,
        "updated_at": updated_at,
    }

    reworks: list[dict[str, Any]] = []
    for row in rework_rows:
        reworks.append({
            "timestamp": row.get("timestamp", ""),
            "project_id": row.get("project_id", ""),
            "scene_ref": row.get("scene_ref", ""),
            "note": row.get("note", ""),
            "tags": _loads_json(row.get("tags_json"), []),
            "status": row.get("status", "open"),
        })

    return {
        "project_id": str(project_id or "").strip(),
        "project_profile": project_profile,
        "character_profiles": character_profiles,
        "recent_reworks": reworks[-20:],
    }


def update_project_profile(project_id: str, profile: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    row = fetch_project_profile_row(project_id)
    current = {
        "project_id": str(project_id or "").strip(),
        "profile": _loads_json(row.get("profile_json"), {}) if row else {},
        "locked_fields": _loads_json(row.get("locked_fields_json"), []) if row else [],
        "created_at": row.get("created_at", _utc_now_iso()) if row else _utc_now_iso(),
        "updated_at": row.get("updated_at", _utc_now_iso()) if row else _utc_now_iso(),
    }
    current_profile = dict(current.get("profile", {}))
    merged_profile = _merge_locked(
        {**current_profile, "locked_fields": current.get("locked_fields", [])},
        profile,
        PROJECT_LOCKABLE_FIELDS,
        force=force,
    )
    updated = {
        "project_id": str(project_id or "").strip(),
        "profile": {k: v for k, v in merged_profile.items() if k not in {"locked_fields", "created_at", "updated_at"}},
        "locked_fields": merged_profile.get("locked_fields", []),
        "created_at": current.get("created_at", _utc_now_iso()),
        "updated_at": merged_profile.get("updated_at", _utc_now_iso()),
    }
    upsert_project_profile_row(
        str(project_id or "").strip(),
        updated["profile"],
        updated["locked_fields"],
        updated["created_at"],
        updated["updated_at"],
    )
    return updated


def upsert_character_profile(project_id: str, character_name: str, profile: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    key = str(character_name or "").strip()
    if not key:
        raise ValueError("character_name is required")
    current_map = {row.get("character_name", ""): row for row in fetch_character_rows(project_id)}
    row = current_map.get(key)
    existing_profile = _loads_json(row.get("profile_json"), {}) if row else {"name": key}
    existing_profile["name"] = key
    existing_profile["locked_fields"] = _loads_json(row.get("locked_fields_json"), []) if row else []
    existing_profile["created_at"] = row.get("created_at", _utc_now_iso()) if row else _utc_now_iso()
    existing_profile["updated_at"] = row.get("updated_at", _utc_now_iso()) if row else _utc_now_iso()

    merged = _merge_locked(
        existing_profile,
        {"name": key, **profile},
        CHARACTER_LOCKABLE_FIELDS,
        force=force,
    )
    upsert_character_row(
        str(project_id or "").strip(),
        key,
        {k: v for k, v in merged.items() if k not in {"locked_fields", "created_at", "updated_at"}},
        merged.get("locked_fields", []),
        merged.get("created_at", _utc_now_iso()),
        merged.get("updated_at", _utc_now_iso()),
    )
    return merged


def add_rework_note(project_id: str, note: str, *, scene_ref: str = "", tags: list[str] | None = None, status: str = "open") -> dict[str, Any]:
    record = {
        "timestamp": _utc_now_iso(),
        "project_id": str(project_id or "").strip(),
        "scene_ref": str(scene_ref or "").strip(),
        "note": str(note or "").strip(),
        "tags": [str(tag).strip() for tag in (tags or []) if str(tag).strip()],
        "status": str(status or "open").strip(),
    }
    insert_rework_row(
        record["project_id"],
        record["scene_ref"],
        record["note"],
        record["tags"],
        record["status"],
        record["timestamp"],
    )
    return record


def build_memory_context(project_id: str, *, character_names: list[str] | None = None) -> str:
    memory = get_project_memory(project_id)
    profile = memory.get("project_profile", {}).get("profile", {})
    project_lines = []
    for key in ["genre", "theme", "style", "tone", "visual_style", "pace", "audience", "do_not_change"]:
        value = profile.get(key)
        if isinstance(value, list):
            value = "/".join(str(v).strip() for v in value if str(v).strip())
        if value:
            project_lines.append(f"{key}: {value}")

    characters = memory.get("character_profiles", {}).get("characters", {})
    wanted = [str(name).strip() for name in (character_names or []) if str(name).strip()]
    if not wanted:
        wanted = list(characters.keys())[:5]

    selected_characters = []
    for name in wanted:
        info = characters.get(name)
        if not info:
            continue
        summary_parts = []
        for key in ["role", "persona", "traits", "relationship", "signature_lines", "visual_tags", "do_not_change"]:
            value = info.get(key)
            if isinstance(value, list):
                value = "/".join(str(v).strip() for v in value if str(v).strip())
            if value:
                summary_parts.append(f"{key}: {value}")
        if summary_parts:
            selected_characters.append(f"?? {name} -> " + " | ".join(summary_parts))

    recent_reworks = memory.get("recent_reworks", [])[-3:]
    rework_lines = []
    for item in recent_reworks:
        note = str(item.get("note", "")).strip()
        if note:
            scene_ref = str(item.get("scene_ref", "")).strip()
            prefix = f"{scene_ref}: " if scene_ref else ""
            rework_lines.append(prefix + note)

    parts = []
    if project_lines:
        parts.append("\u9879\u76ee\u8bb0\u5fc6\n" + "\n".join(project_lines))
    if selected_characters:
        parts.append("\u89d2\u8272\u8bb0\u5fc6\n" + "\n".join(selected_characters))
    if rework_lines:
        parts.append("\u8fd4\u5de5\u8bb0\u5f55\n" + "\n".join(rework_lines))
    return "\n\n".join(parts)
