from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db_compat import get_conn
from .paths import safe_path_segment


ROOT_DIR = Path(__file__).resolve().parents[3]
PROJECTS_DIR = ROOT_DIR / "storage" / "projects"
GLOBAL_TRACE_FILE = ROOT_DIR / "storage" / "director_runs" / "director_trace.jsonl"
GLOBAL_EVOLUTION_FILE = ROOT_DIR / "storage" / "director_evolution" / "cases.jsonl"

_TABLES_READY = False


def ensure_director_tables() -> None:
    global _TABLES_READY
    if _TABLES_READY:
        return
    sql = """
    CREATE TABLE IF NOT EXISTS director_project_profiles (
        project_id TEXT PRIMARY KEY,
        profile_json TEXT NOT NULL DEFAULT '{}',
        locked_fields_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS director_character_profiles (
        project_id TEXT NOT NULL,
        character_name TEXT NOT NULL,
        profile_json TEXT NOT NULL DEFAULT '{}',
        locked_fields_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (project_id, character_name)
    );

    CREATE TABLE IF NOT EXISTS director_rework_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL,
        scene_ref TEXT,
        note TEXT NOT NULL,
        tags_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'open',
        timestamp TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS director_trace_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        project_id TEXT,
        event_type TEXT NOT NULL,
        preset_key TEXT,
        filter_mode TEXT,
        filter_value TEXT,
        effective_filter_mode TEXT,
        effective_filter_value TEXT,
        stage TEXT,
        scene_count INTEGER,
        shot_count INTEGER,
        matched_library_families_json TEXT NOT NULL DEFAULT '[]',
        matched_library_clusters_json TEXT NOT NULL DEFAULT '[]',
        source_files_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'success',
        message TEXT,
        extra_json TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS director_evolution_cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id TEXT NOT NULL UNIQUE,
        timestamp TEXT NOT NULL,
        project_id TEXT,
        output_name TEXT,
        verdict_type TEXT NOT NULL,
        verdict_label TEXT,
        primary_problem TEXT,
        case_tags_json TEXT NOT NULL DEFAULT '[]',
        manual_notes TEXT,
        evaluation_result_json TEXT NOT NULL DEFAULT '{}',
        run_log_summary_json TEXT NOT NULL DEFAULT '{}',
        reusable_pattern_json TEXT NOT NULL DEFAULT '{}'
    );

    CREATE INDEX IF NOT EXISTS idx_director_rework_project_time ON director_rework_history(project_id, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_director_trace_project_time ON director_trace_events(project_id, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_director_trace_event_type ON director_trace_events(event_type, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_director_evolution_project_time ON director_evolution_cases(project_id, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_director_evolution_problem ON director_evolution_cases(primary_problem, verdict_type, timestamp DESC);
    """
    with get_conn() as conn:
        conn.executescript(sql)
    _TABLES_READY = True


def _loads_json(text: str | None, default: Any) -> Any:
    try:
        if text is None or text == "":
            return default
        return json.loads(text)
    except Exception:
        return default


def _dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _legacy_memory_root(project_id: str) -> Path:
    return PROJECTS_DIR / safe_path_segment(project_id, default="project") / "director_memory"


def _migrate_memory_from_files(project_id: str) -> None:
    ensure_director_tables()
    normalized = str(project_id or "").strip()
    if not normalized:
        return
    with get_conn() as conn:
        project_exists = conn.execute(
            "SELECT 1 FROM director_project_profiles WHERE project_id = ? LIMIT 1",
            (normalized,),
        ).fetchone()
        character_exists = conn.execute(
            "SELECT 1 FROM director_character_profiles WHERE project_id = ? LIMIT 1",
            (normalized,),
        ).fetchone()
        rework_exists = conn.execute(
            "SELECT 1 FROM director_rework_history WHERE project_id = ? LIMIT 1",
            (normalized,),
        ).fetchone()
    if project_exists and character_exists and rework_exists:
        return

    memory_root = _legacy_memory_root(normalized)
    profile_file = memory_root / "project_profile.json"
    if profile_file.exists() and not project_exists:
        data = _loads_json(profile_file.read_text(encoding="utf-8"), {})
        if isinstance(data, dict):
            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO director_project_profiles(project_id, profile_json, locked_fields_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        normalized,
                        _dumps_json(data.get("profile", {})),
                        _dumps_json(data.get("locked_fields", [])),
                        str(data.get("created_at", "")),
                        str(data.get("updated_at", "")),
                    ),
                )

    character_file = memory_root / "character_profiles.json"
    if character_file.exists() and not character_exists:
        data = _loads_json(character_file.read_text(encoding="utf-8"), {})
        characters = data.get("characters", {}) if isinstance(data, dict) else {}
        if isinstance(characters, dict):
            with get_conn() as conn:
                for name, profile in characters.items():
                    if not isinstance(profile, dict):
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO director_character_profiles(
                            project_id, character_name, profile_json, locked_fields_json, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            normalized,
                            str(name).strip(),
                            _dumps_json({k: v for k, v in profile.items() if k not in {"locked_fields", "created_at", "updated_at"}}),
                            _dumps_json(profile.get("locked_fields", [])),
                            str(profile.get("created_at", "")),
                            str(profile.get("updated_at", "")),
                        ),
                    )

    rework_file = memory_root / "rework_history.jsonl"
    if rework_file.exists() and not rework_exists:
        with get_conn() as conn:
            for raw_line in rework_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                record = _loads_json(line, None)
                if not isinstance(record, dict):
                    continue
                conn.execute(
                    """
                    INSERT INTO director_rework_history(project_id, scene_ref, note, tags_json, status, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized,
                        str(record.get("scene_ref", "")).strip(),
                        str(record.get("note", "")).strip(),
                        _dumps_json(record.get("tags", [])),
                        str(record.get("status", "open")).strip(),
                        str(record.get("timestamp", "")),
                    ),
                )


def _migrate_trace_from_files(project_id: str = "") -> None:
    ensure_director_tables()
    normalized = str(project_id or "").strip()
    with get_conn() as conn:
        if normalized:
            exists = conn.execute(
                "SELECT 1 FROM director_trace_events WHERE project_id = ? LIMIT 1",
                (normalized,),
            ).fetchone()
            if exists:
                return
            path = PROJECTS_DIR / safe_path_segment(normalized, default="project") / "director" / "trace.jsonl"
        else:
            exists = conn.execute("SELECT 1 FROM director_trace_events LIMIT 1").fetchone()
            if exists:
                return
            path = GLOBAL_TRACE_FILE
    if not path.exists():
        return
    with get_conn() as conn:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            record = _loads_json(line, None)
            if not isinstance(record, dict):
                continue
            conn.execute(
                """
                INSERT INTO director_trace_events(
                    timestamp, project_id, event_type, preset_key, filter_mode, filter_value,
                    effective_filter_mode, effective_filter_value, stage, scene_count, shot_count,
                    matched_library_families_json, matched_library_clusters_json, source_files_json,
                    status, message, extra_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.get("timestamp", "")),
                    str(record.get("project_id", "")).strip(),
                    str(record.get("event_type", "")).strip(),
                    str(record.get("preset_key", "")).strip(),
                    str(record.get("filter_mode", "")).strip(),
                    str(record.get("filter_value", "")).strip(),
                    str(record.get("effective_filter_mode", "")).strip(),
                    str(record.get("effective_filter_value", "")).strip(),
                    str(record.get("stage", "")).strip(),
                    record.get("scene_count"),
                    record.get("shot_count"),
                    _dumps_json(record.get("matched_library_families", [])),
                    _dumps_json(record.get("matched_library_clusters", [])),
                    _dumps_json(record.get("source_files", [])),
                    str(record.get("status", "success")).strip(),
                    str(record.get("message", "")).strip(),
                    _dumps_json(record.get("extra", {})),
                ),
            )


def _migrate_evolution_from_files(project_id: str = "") -> None:
    ensure_director_tables()
    normalized = str(project_id or "").strip()
    with get_conn() as conn:
        if normalized:
            exists = conn.execute(
                "SELECT 1 FROM director_evolution_cases WHERE project_id = ? LIMIT 1",
                (normalized,),
            ).fetchone()
            if exists:
                return
            path = PROJECTS_DIR / safe_path_segment(normalized, default="project") / "director" / "evolution_cases.jsonl"
        else:
            exists = conn.execute("SELECT 1 FROM director_evolution_cases LIMIT 1").fetchone()
            if exists:
                return
            path = GLOBAL_EVOLUTION_FILE
    if not path.exists():
        return
    with get_conn() as conn:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            record = _loads_json(line, None)
            if not isinstance(record, dict):
                continue
            case_record = record.get("case_record", {}) if isinstance(record.get("case_record"), dict) else {}
            reusable_pattern = record.get("reusable_pattern", {}) if isinstance(record.get("reusable_pattern"), dict) else {}
            case_id = str(case_record.get("case_id", "")).strip()
            if not case_id:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO director_evolution_cases(
                    case_id, timestamp, project_id, output_name, verdict_type, verdict_label,
                    primary_problem, case_tags_json, manual_notes, evaluation_result_json,
                    run_log_summary_json, reusable_pattern_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    str(case_record.get("timestamp", "")),
                    str(case_record.get("project_id", "")).strip(),
                    str(case_record.get("output_name", "")).strip(),
                    str(case_record.get("verdict_type", "")).strip(),
                    str(case_record.get("manual_verdict", "")).strip(),
                    str(reusable_pattern.get("primary_problem", case_record.get("primary_problem", ""))).strip(),
                    _dumps_json(case_record.get("case_tags", [])),
                    str(case_record.get("manual_notes", "")).strip(),
                    _dumps_json(case_record.get("evaluation_result", {})),
                    _dumps_json(case_record.get("run_log_summary", {})),
                    _dumps_json(reusable_pattern),
                ),
            )


def fetch_project_profile_row(project_id: str) -> dict[str, Any] | None:
    ensure_director_tables()
    _migrate_memory_from_files(project_id)
    normalized = str(project_id or "").strip()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM director_project_profiles WHERE project_id = ?",
            (normalized,),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def upsert_project_profile_row(project_id: str, profile: dict[str, Any], locked_fields: list[str], created_at: str, updated_at: str) -> None:
    ensure_director_tables()
    normalized = str(project_id or "").strip()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO director_project_profiles(project_id, profile_json, locked_fields_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (normalized, _dumps_json(profile), _dumps_json(locked_fields), created_at, updated_at),
        )


def fetch_character_rows(project_id: str) -> list[dict[str, Any]]:
    ensure_director_tables()
    _migrate_memory_from_files(project_id)
    normalized = str(project_id or "").strip()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM director_character_profiles WHERE project_id = ? ORDER BY character_name",
            (normalized,),
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_character_row(project_id: str, character_name: str, profile: dict[str, Any], locked_fields: list[str], created_at: str, updated_at: str) -> None:
    ensure_director_tables()
    normalized = str(project_id or "").strip()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO director_character_profiles(
                project_id, character_name, profile_json, locked_fields_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (normalized, str(character_name).strip(), _dumps_json(profile), _dumps_json(locked_fields), created_at, updated_at),
        )


def fetch_rework_rows(project_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    ensure_director_tables()
    _migrate_memory_from_files(project_id)
    normalized = str(project_id or "").strip()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM director_rework_history WHERE project_id = ? ORDER BY timestamp DESC, id DESC LIMIT ?",
            (normalized, int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def insert_rework_row(project_id: str, scene_ref: str, note: str, tags: list[str], status: str, timestamp: str) -> None:
    ensure_director_tables()
    normalized = str(project_id or "").strip()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO director_rework_history(project_id, scene_ref, note, tags_json, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (normalized, scene_ref, note, _dumps_json(tags), status, timestamp),
        )


def insert_trace_row(record: dict[str, Any]) -> None:
    ensure_director_tables()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO director_trace_events(
                timestamp, project_id, event_type, preset_key, filter_mode, filter_value,
                effective_filter_mode, effective_filter_value, stage, scene_count, shot_count,
                matched_library_families_json, matched_library_clusters_json, source_files_json,
                status, message, extra_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(record.get("timestamp", "")),
                str(record.get("project_id", "")).strip(),
                str(record.get("event_type", "")).strip(),
                str(record.get("preset_key", "")).strip(),
                str(record.get("filter_mode", "")).strip(),
                str(record.get("filter_value", "")).strip(),
                str(record.get("effective_filter_mode", "")).strip(),
                str(record.get("effective_filter_value", "")).strip(),
                str(record.get("stage", "")).strip(),
                record.get("scene_count"),
                record.get("shot_count"),
                _dumps_json(record.get("matched_library_families", [])),
                _dumps_json(record.get("matched_library_clusters", [])),
                _dumps_json(record.get("source_files", [])),
                str(record.get("status", "success")).strip(),
                str(record.get("message", "")).strip(),
                _dumps_json(record.get("extra", {})),
            ),
        )


def fetch_trace_rows(project_id: str = "", *, limit: int = 20, event_type: str = "") -> list[dict[str, Any]]:
    ensure_director_tables()
    _migrate_trace_from_files(project_id)
    normalized = str(project_id or "").strip()
    normalized_event = str(event_type or "").strip()
    sql = "SELECT * FROM director_trace_events"
    params: list[Any] = []
    clauses: list[str] = []
    if normalized:
        clauses.append("project_id = ?")
        params.append(normalized)
    if normalized_event:
        clauses.append("event_type = ?")
        params.append(normalized_event)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(row) for row in reversed(rows)]


def insert_evolution_row(case_record: dict[str, Any], reusable_pattern: dict[str, Any]) -> None:
    ensure_director_tables()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO director_evolution_cases(
                case_id, timestamp, project_id, output_name, verdict_type, verdict_label,
                primary_problem, case_tags_json, manual_notes, evaluation_result_json,
                run_log_summary_json, reusable_pattern_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(case_record.get("case_id", "")).strip(),
                str(case_record.get("timestamp", "")).strip(),
                str(case_record.get("project_id", "")).strip(),
                str(case_record.get("output_name", "")).strip(),
                str(case_record.get("verdict_type", "")).strip(),
                str(case_record.get("manual_verdict", "")).strip(),
                str(reusable_pattern.get("primary_problem", case_record.get("primary_problem", ""))).strip(),
                _dumps_json(case_record.get("case_tags", [])),
                str(case_record.get("manual_notes", "")).strip(),
                _dumps_json(case_record.get("evaluation_result", {})),
                _dumps_json(case_record.get("run_log_summary", {})),
                _dumps_json(reusable_pattern),
            ),
        )


def fetch_evolution_rows(project_id: str = "", *, problem_type: str = "", verdict_type: str = "", limit: int = 20) -> list[dict[str, Any]]:
    ensure_director_tables()
    _migrate_evolution_from_files(project_id)
    normalized = str(project_id or "").strip()
    normalized_problem = str(problem_type or "").strip().lower()
    normalized_verdict = str(verdict_type or "").strip().lower()
    sql = "SELECT * FROM director_evolution_cases"
    params: list[Any] = []
    clauses: list[str] = []
    if normalized:
        clauses.append("project_id = ?")
        params.append(normalized)
    if normalized_problem:
        clauses.append("LOWER(primary_problem) = ?")
        params.append(normalized_problem)
    if normalized_verdict:
        clauses.append("LOWER(verdict_type) = ?")
        params.append(normalized_verdict)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(row) for row in reversed(rows)]
