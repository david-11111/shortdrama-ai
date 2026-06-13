from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import safe_path_segment
from .store import fetch_trace_rows, insert_trace_row


ROOT_DIR = Path(__file__).resolve().parents[3]
GLOBAL_TRACE_FILE = ROOT_DIR / "storage" / "director_runs" / "director_trace.jsonl"
PROJECT_STORAGE_DIR = ROOT_DIR / "storage" / "projects"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _loads_json(text: str | None, default: Any) -> Any:
    try:
        if text is None or text == "":
            return default
        return json.loads(text)
    except Exception:
        return default


def log_director_event(
    *,
    event_type: str,
    project_id: str = "",
    preset_key: str = "",
    filter_mode: str = "",
    filter_value: str = "",
    effective_filter_mode: str = "",
    effective_filter_value: str = "",
    stage: str = "",
    scene_count: int | None = None,
    shot_count: int | None = None,
    matched_library_families: list[str] | None = None,
    matched_library_clusters: list[str] | None = None,
    source_files: list[str] | None = None,
    status: str = "success",
    message: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "timestamp": _utc_now_iso(),
        "project_id": str(project_id or "").strip(),
        "event_type": str(event_type or "").strip(),
        "preset_key": str(preset_key or "").strip(),
        "filter_mode": str(filter_mode or "").strip(),
        "filter_value": str(filter_value or "").strip(),
        "effective_filter_mode": str(effective_filter_mode or "").strip(),
        "effective_filter_value": str(effective_filter_value or "").strip(),
        "stage": str(stage or "").strip(),
        "scene_count": scene_count,
        "shot_count": shot_count,
        "matched_library_families": sorted(set(matched_library_families or [])),
        "matched_library_clusters": sorted(set(matched_library_clusters or [])),
        "source_files": sorted(set(source_files or [])),
        "status": str(status or "success").strip(),
        "message": str(message or "").strip(),
        "extra": extra or {},
    }
    insert_trace_row(record)
    _append_jsonl(GLOBAL_TRACE_FILE, record)
    if record["project_id"]:
        _append_jsonl(PROJECT_STORAGE_DIR / safe_path_segment(record["project_id"], default="project") / "director" / "trace.jsonl", record)
    return record


def summarize_library_hits(matches: list[dict[str, Any]]) -> dict[str, list[str]]:
    families = []
    clusters = []
    sources = []
    for item in matches or []:
        family = str(item.get("library_family", "")).strip()
        cluster = str(item.get("library_cluster", "")).strip()
        source_file = str(item.get("source_file", "")).strip()
        if family:
            families.append(family)
        if cluster:
            clusters.append(cluster)
        if source_file:
            sources.append(source_file)
    return {
        "families": sorted(set(families)),
        "clusters": sorted(set(clusters)),
        "sources": sorted(set(sources)),
    }


def load_trace_records(project_id: str = "", *, limit: int = 20, event_type: str = "") -> list[dict[str, Any]]:
    rows = fetch_trace_rows(project_id, limit=limit, event_type=event_type)
    records: list[dict[str, Any]] = []
    for row in rows:
        records.append({
            "timestamp": row.get("timestamp", ""),
            "project_id": row.get("project_id", ""),
            "event_type": row.get("event_type", ""),
            "preset_key": row.get("preset_key", ""),
            "filter_mode": row.get("filter_mode", ""),
            "filter_value": row.get("filter_value", ""),
            "effective_filter_mode": row.get("effective_filter_mode", ""),
            "effective_filter_value": row.get("effective_filter_value", ""),
            "stage": row.get("stage", ""),
            "scene_count": row.get("scene_count"),
            "shot_count": row.get("shot_count"),
            "matched_library_families": _loads_json(row.get("matched_library_families_json"), []),
            "matched_library_clusters": _loads_json(row.get("matched_library_clusters_json"), []),
            "source_files": _loads_json(row.get("source_files_json"), []),
            "status": row.get("status", "success"),
            "message": row.get("message", ""),
            "extra": _loads_json(row.get("extra_json"), {}),
        })
    return records
