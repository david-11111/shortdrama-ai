from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .explainer import explain_run
from .paths import safe_path_segment
from .store import fetch_evolution_rows, insert_evolution_row


ROOT_DIR = Path(__file__).resolve().parents[3]
GLOBAL_EVOLUTION_DIR = ROOT_DIR / "storage" / "director_evolution"
GLOBAL_CASES_FILE = GLOBAL_EVOLUTION_DIR / "cases.jsonl"
PROJECTS_DIR = ROOT_DIR / "storage" / "projects"

SUCCESS_VERDICTS = {"accept", "accepted", "pass", "passed", "success", "approved", "ok"}
FAIL_VERDICTS = {"reject", "rejected", "fail", "failed", "discard"}
REWORK_VERDICTS = {"revise", "rework", "retry", "iterate", "needs_rework"}


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


def _normalize_verdict(manual_verdict: str, evaluation_result: dict[str, Any] | None = None) -> tuple[str, str]:
    raw = str(manual_verdict or "").strip()
    normalized = raw.lower().replace(" ", "_")
    if normalized in SUCCESS_VERDICTS:
        return "success", raw or "accept"
    if normalized in FAIL_VERDICTS:
        return "failure", raw or "reject"
    if normalized in REWORK_VERDICTS:
        return "rework", raw or "rework"

    evaluation_result = evaluation_result or {}
    total_score = int(evaluation_result.get("total_score", 0) or 0)
    grade = str(evaluation_result.get("grade", "")).strip().upper()
    if total_score >= 90 or grade == "A":
        return "success", raw or "accept"
    if total_score < 60 or grade == "D":
        return "failure", raw or "reject"
    return "rework", raw or "rework"


def _primary_problem(evaluation_result: dict[str, Any] | None = None) -> str:
    evaluation_result = evaluation_result or {}
    weakest = str(evaluation_result.get("weakest_dimension", "")).strip().lower()
    if weakest:
        return weakest
    problems = evaluation_result.get("problem_types", []) or []
    for item in problems:
        value = str(item or "").strip().lower()
        if value:
            return value
    return "structure"


def _load_cases(project_id: str = "") -> list[dict[str, Any]]:
    rows = fetch_evolution_rows(project_id, limit=100000)
    records: list[dict[str, Any]] = []
    for row in rows:
        case_record = {
            "case_id": row.get("case_id", ""),
            "timestamp": row.get("timestamp", ""),
            "project_id": row.get("project_id", ""),
            "output_name": row.get("output_name", ""),
            "manual_verdict": row.get("verdict_label", ""),
            "verdict_type": row.get("verdict_type", ""),
            "manual_notes": row.get("manual_notes", ""),
            "case_tags": _loads_json(row.get("case_tags_json"), []),
            "primary_problem": row.get("primary_problem", ""),
            "evaluation_result": _loads_json(row.get("evaluation_result_json"), {}),
            "run_log_summary": _loads_json(row.get("run_log_summary_json"), {}),
        }
        records.append({
            "case_record": case_record,
            "reusable_pattern": _loads_json(row.get("reusable_pattern_json"), {}),
        })
    return records


def _build_reusable_pattern(
    *,
    case_id: str,
    verdict_type: str,
    verdict_label: str,
    project_id: str,
    output_name: str,
    evaluation_result: dict[str, Any],
    run_log: dict[str, Any],
) -> dict[str, Any]:
    scores = evaluation_result.get("scores", {}) or {}
    primary_problem = _primary_problem(evaluation_result)
    summary = run_log.get("summary", {}) if isinstance(run_log, dict) else {}
    preset_keys = summary.get("preset_keys", []) if isinstance(summary, dict) else []
    matched_families = summary.get("matched_library_families", []) if isinstance(summary, dict) else []
    matched_clusters = summary.get("matched_library_clusters", []) if isinstance(summary, dict) else []
    score_snapshot = {
        key: int((value or {}).get("score", 0) or 0)
        for key, value in scores.items()
        if isinstance(value, dict)
    }

    if verdict_type == "success":
        reuse_mode = "promote"
        pattern_summary = (
            f"\u8fd9\u662f\u4e00\u6761\u53ef\u590d\u7528\u7684\u6210\u529f\u6848\u4f8b\uff0c\u53ef\u4f18\u5148\u4f5c\u4e3a\u300c{primary_problem}\u300d\u7c7b\u4efb\u52a1\u7684\u53c2\u8003\u6a21\u5f0f\u3002"
        )
    elif verdict_type == "failure":
        reuse_mode = "avoid"
        pattern_summary = (
            f"\u8fd9\u662f\u4e00\u6761\u5931\u8d25\u6848\u4f8b\uff0c\u540e\u7eed\u9047\u5230\u300c{primary_problem}\u300d\u7c7b\u4efb\u52a1\u65f6\u5e94\u907f\u514d\u76f4\u63a5\u590d\u5236\u672c\u6b21\u914d\u7f6e\u3002"
        )
    else:
        reuse_mode = "refine"
        pattern_summary = (
            f"\u8fd9\u662f\u4e00\u6761\u8fd4\u4fee\u6848\u4f8b\uff0c\u9002\u5408\u7528\u4e8e\u300c{primary_problem}\u300d\u7c7b\u4efb\u52a1\u7684\u8fed\u4ee3\u8c03\u6574\u53c2\u8003\u3002"
        )

    return {
        "case_id": case_id,
        "project_id": project_id,
        "output_name": output_name,
        "verdict_type": verdict_type,
        "verdict_label": verdict_label,
        "primary_problem": primary_problem,
        "reuse_mode": reuse_mode,
        "recommended_preset_keys": preset_keys,
        "matched_library_families": matched_families,
        "matched_library_clusters": matched_clusters,
        "score_snapshot": score_snapshot,
        "pattern_summary": pattern_summary,
    }


def record_case(
    *,
    project_id: str = "",
    output_name: str = "",
    run_log: dict[str, Any] | None = None,
    evaluation_result: dict[str, Any] | None = None,
    manual_verdict: str = "",
    manual_notes: str = "",
    case_tags: list[str] | None = None,
) -> dict[str, Any]:
    normalized_project = str(project_id or "").strip()
    normalized_output = str(output_name or "").strip()
    evaluation_result = evaluation_result or {}

    if not run_log:
        run_log = explain_run(normalized_project, limit=30) if normalized_project else {"records": [], "summary": {}}

    verdict_type, verdict_label = _normalize_verdict(manual_verdict, evaluation_result)
    primary_problem = _primary_problem(evaluation_result)
    timestamp = _utc_now_iso()
    case_id = f"{normalized_project or 'global'}::{normalized_output or 'default'}::{timestamp}"

    case_record = {
        "case_id": case_id,
        "timestamp": timestamp,
        "project_id": normalized_project,
        "output_name": normalized_output,
        "manual_verdict": verdict_label,
        "verdict_type": verdict_type,
        "manual_notes": str(manual_notes or "").strip(),
        "case_tags": [str(item).strip() for item in (case_tags or []) if str(item).strip()],
        "primary_problem": primary_problem,
        "evaluation_result": evaluation_result,
        "run_log_summary": (run_log or {}).get("summary", {}),
    }
    reusable_pattern = _build_reusable_pattern(
        case_id=case_id,
        verdict_type=verdict_type,
        verdict_label=verdict_label,
        project_id=normalized_project,
        output_name=normalized_output,
        evaluation_result=evaluation_result,
        run_log=run_log or {},
    )

    record = {
        "case_record": case_record,
        "reusable_pattern": reusable_pattern,
    }
    insert_evolution_row(case_record, reusable_pattern)
    _append_jsonl(GLOBAL_CASES_FILE, record)
    if normalized_project:
        _append_jsonl(PROJECTS_DIR / safe_path_segment(normalized_project, default="project") / "director" / "evolution_cases.jsonl", record)
    return record


def list_patterns(
    *,
    project_id: str = "",
    problem_type: str = "",
    verdict_type: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    rows = fetch_evolution_rows(project_id, problem_type=problem_type, verdict_type=verdict_type, limit=limit)

    filtered: list[dict[str, Any]] = []
    for row in rows:
        case_record = {
            "case_id": row.get("case_id", ""),
            "timestamp": row.get("timestamp", ""),
            "project_id": row.get("project_id", ""),
            "output_name": row.get("output_name", ""),
            "manual_verdict": row.get("verdict_label", ""),
            "verdict_type": row.get("verdict_type", ""),
            "manual_notes": row.get("manual_notes", ""),
            "case_tags": _loads_json(row.get("case_tags_json"), []),
            "primary_problem": row.get("primary_problem", ""),
            "evaluation_result": _loads_json(row.get("evaluation_result_json"), {}),
            "run_log_summary": _loads_json(row.get("run_log_summary_json"), {}),
        }
        filtered.append({
            "case_record": case_record,
            "reusable_pattern": _loads_json(row.get("reusable_pattern_json"), {}),
        })

    verdict_counts: dict[str, int] = {}
    problem_counts: dict[str, int] = {}
    preset_counts: dict[str, int] = {}
    for item in filtered:
        case_record = item.get("case_record", {}) if isinstance(item, dict) else {}
        pattern = item.get("reusable_pattern", {}) if isinstance(item, dict) else {}
        verdict = str(case_record.get("verdict_type", "")).strip()
        problem = str(pattern.get("primary_problem", "")).strip()
        if verdict:
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        if problem:
            problem_counts[problem] = problem_counts.get(problem, 0) + 1
        for preset in pattern.get("recommended_preset_keys", []) or []:
            key = str(preset or "").strip()
            if key:
                preset_counts[key] = preset_counts.get(key, 0) + 1

    patterns = [item.get("reusable_pattern", {}) for item in filtered]
    return {
        "project_id": str(project_id or "").strip(),
        "problem_type": str(problem_type or "").strip().lower(),
        "verdict_type": str(verdict_type or "").strip().lower(),
        "total": len(filtered),
        "summary": {
            "verdict_counts": verdict_counts,
            "problem_counts": problem_counts,
            "preset_counts": preset_counts,
        },
        "patterns": patterns,
        "cases": [item.get("case_record", {}) for item in filtered],
    }
