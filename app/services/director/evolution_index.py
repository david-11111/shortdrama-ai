from __future__ import annotations

import re
from threading import RLock
from typing import Any

from .store import fetch_evolution_rows


_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_SPLIT_RE = re.compile(r"[\s,.;?/|:()\[\]<>\'\"，。；：？！、“”‘’、]+")
_MAX_LOAD = 100000


def _extract_terms(text: str) -> list[str]:
    raw_terms = []
    lowered = str(text or "").lower()
    for item in _SPLIT_RE.split(lowered):
        token = item.strip()
        if len(token) >= 2:
            raw_terms.append(token)
    for chunk in _CJK_RE.findall(str(text or "")):
        chunk = chunk.strip()
        length = len(chunk)
        for size in range(2, min(4, length) + 1):
            for idx in range(0, length - size + 1):
                raw_terms.append(chunk[idx:idx + size])
    return list(dict.fromkeys(raw_terms))


def _build_case_text(case_record: dict[str, Any], reusable_pattern: dict[str, Any]) -> str:
    evaluation = case_record.get("evaluation_result", {}) if isinstance(case_record, dict) else {}
    scores = evaluation.get("scores", {}) if isinstance(evaluation, dict) else {}
    score_parts = []
    for key, value in scores.items():
        if isinstance(value, dict):
            score_parts.append(f"{key}:{value.get('score', 0)}")
    parts = [
        case_record.get("output_name", ""),
        case_record.get("manual_verdict", ""),
        case_record.get("manual_notes", ""),
        " ".join(case_record.get("case_tags", []) or []),
        case_record.get("primary_problem", ""),
        evaluation.get("weakest_dimension", "") if isinstance(evaluation, dict) else "",
        " ".join(evaluation.get("problem_types", []) or []) if isinstance(evaluation, dict) else "",
        " ".join(evaluation.get("review_notes", []) or []) if isinstance(evaluation, dict) else "",
        " ".join(score_parts),
        reusable_pattern.get("primary_problem", ""),
        reusable_pattern.get("verdict_type", ""),
        reusable_pattern.get("reuse_mode", ""),
        reusable_pattern.get("pattern_summary", ""),
        " ".join(reusable_pattern.get("recommended_preset_keys", []) or []),
        " ".join(reusable_pattern.get("matched_library_families", []) or []),
        " ".join(reusable_pattern.get("matched_library_clusters", []) or []),
    ]
    return "\n".join(str(part or "").strip() for part in parts if str(part or "").strip())


class EvolutionMemoryIndex:
    def __init__(self) -> None:
        self._lock = RLock()
        self._loaded = False
        self._entries: dict[str, dict[str, Any]] = {}

    def _row_to_entry(self, row: dict[str, Any]) -> dict[str, Any]:
        case_record = row.get("case_record", {}) if isinstance(row.get("case_record"), dict) else {}
        reusable_pattern = row.get("reusable_pattern", {}) if isinstance(row.get("reusable_pattern"), dict) else {}
        text = _build_case_text(case_record, reusable_pattern)
        return {
            "case_id": str(case_record.get("case_id", "")).strip(),
            "project_id": str(case_record.get("project_id", "")).strip(),
            "output_name": str(case_record.get("output_name", "")).strip(),
            "verdict_type": str(case_record.get("verdict_type", "")).strip().lower(),
            "primary_problem": str(reusable_pattern.get("primary_problem", case_record.get("primary_problem", ""))).strip().lower(),
            "timestamp": str(case_record.get("timestamp", "")).strip(),
            "text": text,
            "terms": set(_extract_terms(text)),
            "case_record": case_record,
            "reusable_pattern": reusable_pattern,
        }

    def rebuild(self, project_id: str = "") -> None:
        rows = fetch_evolution_rows(project_id, limit=_MAX_LOAD)
        entries: dict[str, dict[str, Any]] = {}
        for row in rows:
            case_record = {
                "case_id": row.get("case_id", ""),
                "timestamp": row.get("timestamp", ""),
                "project_id": row.get("project_id", ""),
                "output_name": row.get("output_name", ""),
                "manual_verdict": row.get("verdict_label", ""),
                "verdict_type": row.get("verdict_type", ""),
                "manual_notes": row.get("manual_notes", ""),
                "case_tags": row.get("case_tags", []) or [],
                "primary_problem": row.get("primary_problem", ""),
                "evaluation_result": row.get("evaluation_result", {}) or {},
                "run_log_summary": row.get("run_log_summary", {}) or {},
            }
            reusable_pattern = row.get("reusable_pattern", {}) or {}
            entry = self._row_to_entry({"case_record": case_record, "reusable_pattern": reusable_pattern})
            if entry["case_id"]:
                entries[entry["case_id"]] = entry
        with self._lock:
            if project_id:
                normalized = str(project_id or "").strip()
                self._entries = {key: value for key, value in self._entries.items() if value.get("project_id") != normalized}
                self._entries.update(entries)
            else:
                self._entries = entries
            self._loaded = True

    def ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
        self.rebuild()

    def upsert_case_record(self, record: dict[str, Any]) -> None:
        entry = self._row_to_entry(record)
        case_id = entry.get("case_id", "")
        if not case_id:
            return
        with self._lock:
            self._entries[case_id] = entry
            self._loaded = True

    def _iter_candidates(self, project_id: str = "", problem_type: str = "", verdict_type: str = "") -> list[dict[str, Any]]:
        self.ensure_loaded()
        normalized_project = str(project_id or "").strip()
        normalized_problem = str(problem_type or "").strip().lower()
        normalized_verdict = str(verdict_type or "").strip().lower()
        with self._lock:
            values = list(self._entries.values())
        candidates = []
        for item in values:
            if normalized_project and item.get("project_id") != normalized_project:
                continue
            if normalized_problem and item.get("primary_problem") != normalized_problem:
                continue
            if normalized_verdict and item.get("verdict_type") != normalized_verdict:
                continue
            candidates.append(item)
        return candidates

    def get_similar_cases(self, query: str, *, project_id: str = "", problem_type: str = "", verdict_type: str = "", limit: int = 5) -> list[dict[str, Any]]:
        query_terms = set(_extract_terms(query))
        candidates = self._iter_candidates(project_id=project_id, problem_type=problem_type, verdict_type=verdict_type)
        scored = []
        for item in candidates:
            terms = item.get("terms", set())
            overlap = len(query_terms & terms)
            if query_terms:
                union = len(query_terms | terms) or 1
                ratio = overlap / union
            else:
                ratio = 0.0
            boost = 0.0
            if problem_type and item.get("primary_problem") == str(problem_type).strip().lower():
                boost += 0.15
            if verdict_type and item.get("verdict_type") == str(verdict_type).strip().lower():
                boost += 0.1
            if project_id and item.get("project_id") == str(project_id).strip():
                boost += 0.05
            score = round(ratio + min(overlap, 6) * 0.03 + boost, 6)
            if overlap > 0 or not query_terms:
                scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1].get("timestamp", "")), reverse=True)
        results = []
        for score, item in scored[: max(0, int(limit))]:
            results.append({
                "score": score,
                "case_record": item.get("case_record", {}),
                "reusable_pattern": item.get("reusable_pattern", {}),
            })
        return results

    def get_best_patterns_by_problem(self, problem_type: str, *, verdict_type: str = "success", limit: int = 5) -> list[dict[str, Any]]:
        candidates = self._iter_candidates(problem_type=problem_type, verdict_type=verdict_type)
        scored = []
        for item in candidates:
            evaluation = item.get("case_record", {}).get("evaluation_result", {})
            total_score = int(evaluation.get("total_score", 0) or 0)
            scored.append((total_score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1].get("timestamp", "")), reverse=True)
        return [item.get("reusable_pattern", {}) for _, item in scored[: max(0, int(limit))]]

    def get_recent_success_patterns(self, *, project_id: str = "", limit: int = 10) -> list[dict[str, Any]]:
        candidates = self._iter_candidates(project_id=project_id, verdict_type="success")
        candidates.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        return [item.get("reusable_pattern", {}) for item in candidates[: max(0, int(limit))]]


_INDEX = EvolutionMemoryIndex()


def get_evolution_index() -> EvolutionMemoryIndex:
    return _INDEX
