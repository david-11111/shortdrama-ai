from __future__ import annotations

from pathlib import Path
from typing import Any

from .memory import get_project_memory
from .paths import safe_path_segment
from .trace import load_trace_records


ROOT_DIR = Path(__file__).resolve().parents[3]
PROJECTS_DIR = ROOT_DIR / "storage" / "projects"

DIMENSION_LABELS = {
    "structure": "结构分",
    "character": "人物分",
    "emotion": "情绪分",
    "stability": "稳定分",
    "aesthetic": "审美分",
}

DIMENSION_WEIGHTS = {
    "structure": 0.20,
    "character": 0.20,
    "emotion": 0.20,
    "stability": 0.15,
    "aesthetic": 0.25,
}

AUTO_REWORK_TOTAL_SCORE_THRESHOLD = 75
AUTO_REWORK_DIMENSION_THRESHOLD = 65

EMOTION_TERMS = [
    "\u60c5\u7eea", "\u6c1b\u56f4", "\u7559\u767d", "\u9057\u61be", "\u5bbf\u547d", "\u514b\u5236", "\u7834\u788e", "\u62c9\u627f", "\u8650\u604b", "\u6cbb\u6108",
    "\u840c\u52a8", "\u5bf9\u89c6", "\u5931\u843d", "\u601d\u5ff5", "\u5fc3\u4e8b", "\u60b2\u4f24", "\u6e29\u67d4", "\u75bc\u611f", "\u6697\u6d41",
]

CHARACTER_TERMS = [
    "\u4eba\u7269", "\u4eba\u8bbe", "\u773c\u795e", "\u795e\u6001", "\u4eea\u6001", "\u6027\u683c", "\u6c14\u8d28", "\u7075\u9b42", "\u5973\u4e3b", "\u7537\u4e3b",
]


def _clip_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _text_blob(*parts: Any) -> str:
    normalized: list[str] = []
    for part in parts:
        if isinstance(part, (list, tuple, set)):
            normalized.extend(str(item or "").strip() for item in part)
        else:
            normalized.append(str(part or "").strip())
    return "\n".join(item for item in normalized if item)


def _collect_character_names(raw_value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(raw_value, list):
        for item in raw_value:
            if isinstance(item, dict):
                value = str(item.get("name", "")).strip()
            else:
                value = str(item or "").strip()
            if value and value not in names:
                names.append(value)
        return names
    text_value = str(raw_value or "").strip()
    if not text_value:
        return names
    normalized = text_value
    for delimiter in [",", "\uFF0C", "\u3001", "/", "|", ";", "\uFF1B", "\n", "\r"]:
        normalized = normalized.replace(delimiter, ",")
    for token in [segment.strip() for segment in normalized.split(",")]:
        if token and token not in names:
            names.append(token)
    return names


def _extract_character_names_from_script(script: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for candidate in (script.get("characters", []), script.get("roles", [])):
        for name in _collect_character_names(candidate):
            if name not in names:
                names.append(name)
    for shot in script.get("shots", []) or []:
        if not isinstance(shot, dict):
            continue
        for key in ("characters", "character", "roles"):
            for name in _collect_character_names(shot.get(key, [])):
                if name not in names:
                    names.append(name)
    return names


def _has_any_term(text: str, terms: list[str]) -> int:
    lowered = str(text or "").lower()
    return sum(1 for term in terms if term and str(term).lower() in lowered)


def _project_output_dir(project_id: str, output_name: str) -> Path | None:
    normalized_project = str(project_id or "").strip()
    normalized_output = str(output_name or "").strip()
    if not normalized_project or not normalized_output:
        return None
    return PROJECTS_DIR / safe_path_segment(normalized_project, default="project") / "director" / safe_path_segment(normalized_output, default="run")


def _score_structure(script: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    shots = [shot for shot in (script.get("shots", []) or []) if isinstance(shot, dict)]
    shot_count = len(shots)
    content_count = sum(1 for shot in shots if str(shot.get("content", "")).strip())
    duration_count = sum(1 for shot in shots if isinstance(shot.get("duration", 0), (int, float)) and float(shot.get("duration", 0)) > 0)
    title_ok = 1 if str(script.get("title", "")).strip() else 0
    style_ok = 1 if str(script.get("style", "")).strip() else 0

    indices = [int(shot.get("index", idx + 1)) for idx, shot in enumerate(shots)]
    ordered_ok = 1 if shot_count > 0 and indices == sorted(indices) else 0
    unique_ok = 1 if shot_count > 0 and len(indices) == len(set(indices)) else 0
    pacing_values = [float(shot.get("duration")) for shot in shots if isinstance(shot.get("duration", 0), (int, float)) and float(shot.get("duration", 0)) > 0]
    pacing_ok = 1 if pacing_values and 2 <= (sum(pacing_values) / len(pacing_values)) <= 8 else 0

    completeness_ratio = (content_count / shot_count) if shot_count else 0
    duration_ratio = (duration_count / shot_count) if shot_count else 0
    score = 0.0
    score += completeness_ratio * 35
    score += duration_ratio * 20
    score += (title_ok + style_ok) / 2 * 15
    score += (ordered_ok + unique_ok) / 2 * 15
    score += pacing_ok * 15

    evidence = {
        "shot_count": shot_count,
        "content_coverage": round(completeness_ratio, 4),
        "duration_coverage": round(duration_ratio, 4),
        "title_present": bool(title_ok),
        "style_present": bool(style_ok),
        "index_order_ok": bool(ordered_ok),
        "index_unique_ok": bool(unique_ok),
        "pacing_ok": bool(pacing_ok),
    }
    return _clip_score(score), evidence


def _score_character(project_id: str, script: dict[str, Any], style_hint: str, context_hint: str) -> tuple[int, dict[str, Any]]:
    shots = [shot for shot in (script.get("shots", []) or []) if isinstance(shot, dict)]
    names = _extract_character_names_from_script(script)
    named_shots = 0
    for shot in shots:
        shot_names: list[str] = []
        for key in ("characters", "character", "roles"):
            shot_names.extend(_collect_character_names(shot.get(key, [])))
        if shot_names:
            named_shots += 1

    memory = get_project_memory(project_id) if str(project_id or "").strip() else {}
    character_profiles = memory.get("character_profiles", {}).get("characters", {}) if isinstance(memory, dict) else {}
    covered_names = [name for name in names if name in character_profiles]
    field_richness = 0.0
    if covered_names:
        richness_values = []
        for name in covered_names:
            profile = character_profiles.get(name, {})
            richness_values.append(sum(1 for key in ["role", "persona", "traits", "relationship", "signature_lines", "visual_tags"] if profile.get(key)))
        field_richness = (sum(richness_values) / len(richness_values)) / 6

    shot_ratio = (named_shots / len(shots)) if shots else 0
    coverage_ratio = (len(covered_names) / len(names)) if names else 0
    cue_hits = min(_has_any_term(_text_blob(style_hint, context_hint, script.get("title", ""), script.get("style", "")), CHARACTER_TERMS), 4)

    score = 0.0
    score += min(len(names), 3) / 3 * 25
    score += shot_ratio * 25
    score += coverage_ratio * 30
    score += field_richness * 10
    score += (cue_hits / 4) * 10

    evidence = {
        "character_names": names,
        "named_shot_ratio": round(shot_ratio, 4),
        "memory_covered_names": covered_names,
        "memory_coverage_ratio": round(coverage_ratio, 4),
        "memory_field_richness": round(field_richness, 4),
        "character_cue_hits": cue_hits,
    }
    return _clip_score(score), evidence


def _score_emotion(project_id: str, script: dict[str, Any], style_hint: str, context_hint: str, preset_key: str) -> tuple[int, dict[str, Any]]:
    shots = [shot for shot in (script.get("shots", []) or []) if isinstance(shot, dict)]
    shot_emotion_fields = 0
    for shot in shots:
        if any(str(shot.get(key, "")).strip() for key in ["atmosphere", "emotion", "beat", "voiceover", "subtext"]):
            shot_emotion_fields += 1

    project_profile = {}
    if str(project_id or "").strip():
        memory = get_project_memory(project_id)
        project_profile = memory.get("project_profile", {}).get("profile", {}) if isinstance(memory, dict) else {}

    text_blob = _text_blob(
        style_hint,
        context_hint,
        script.get("title", ""),
        script.get("style", ""),
        script.get("theme", ""),
        project_profile.get("tone", ""),
        project_profile.get("style", ""),
        [shot.get("content", "") for shot in shots],
        [shot.get("atmosphere", "") for shot in shots],
        [shot.get("emotion", "") for shot in shots],
    )
    emotion_hits = min(_has_any_term(text_blob, EMOTION_TERMS), 8)
    emotion_ratio = (shot_emotion_fields / len(shots)) if shots else 0
    preset_bonus = 1.0 if str(preset_key or "").strip() in {"destiny_cinematic", "character_soul", "cinematic_soul"} else 0.0
    tone_bonus = 1.0 if str(project_profile.get("tone", "")).strip() else 0.0

    score = 0.0
    score += (emotion_hits / 8) * 40
    score += emotion_ratio * 30
    score += preset_bonus * 20
    score += tone_bonus * 10

    evidence = {
        "emotion_term_hits": emotion_hits,
        "emotion_annotated_shot_ratio": round(emotion_ratio, 4),
        "preset_bonus": bool(preset_bonus),
        "project_tone_present": bool(tone_bonus),
    }
    return _clip_score(score), evidence


AESTHETIC_SYSTEM_PROMPT = """你是一位资深影视审美评审专家。你需要对一组视频镜头脚本进行审美评分。

评分维度（每项0-100分）：
1. 镜头语言成熟度：运镜、景别、构图是否有电影感，是否有层次变化
2. 情绪节奏层次感：情绪是否有起伏递进，节奏是否疏密得当
3. 画面高级感：光影、色彩、氛围描述是否有质感，是否避免了廉价感
4. 叙事连贯性：镜头之间是否有逻辑衔接，整体是否讲了一个完整的故事

输出严格JSON格式，不要任何解释：
{"camera_language": 分数, "emotion_rhythm": 分数, "visual_quality": 分数, "narrative_coherence": 分数, "overall": 综合分数, "brief_comment": "一句话点评"}"""


def _score_aesthetic(script: dict[str, Any], style_hint: str, context_hint: str) -> tuple[int, dict[str, Any]]:
    """Call LLM to evaluate aesthetic quality. Falls back to rule-based if LLM unavailable."""
    import json as _json

    shots = [shot for shot in (script.get("shots", []) or []) if isinstance(shot, dict)]
    if not shots:
        return 50, {"method": "fallback", "reason": "no_shots"}

    script_summary = _json.dumps({
        "title": script.get("title", ""),
        "style": script.get("style", ""),
        "shot_count": len(shots),
        "shots": [
            {
                "index": shot.get("index", i + 1),
                "content": str(shot.get("content", ""))[:200],
                "shot_type": shot.get("shot_type", ""),
                "camera_movement": shot.get("camera_movement", ""),
                "lighting": shot.get("lighting", ""),
                "atmosphere": shot.get("atmosphere", ""),
                "emotion": shot.get("emotion", ""),
                "duration": shot.get("duration", 0),
            }
            for i, shot in enumerate(shots[:12])
        ],
    }, ensure_ascii=False)

    user_text = f"[风格] {style_hint}\n[背景] {context_hint}\n[脚本]\n{script_summary}"

    try:
        from .doubao import _call_doubao
        raw = _call_doubao([
            {"role": "system", "content": [{"type": "input_text", "text": AESTHETIC_SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_text}]},
        ], timeout=30)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        result = _json.loads(raw)
        overall = int(result.get("overall", 50))
        return _clip_score(overall), {
            "method": "llm",
            "camera_language": result.get("camera_language"),
            "emotion_rhythm": result.get("emotion_rhythm"),
            "visual_quality": result.get("visual_quality"),
            "narrative_coherence": result.get("narrative_coherence"),
            "brief_comment": result.get("brief_comment", ""),
        }
    except Exception as exc:
        variety_count = len(set(shot.get("shot_type", "") for shot in shots if shot.get("shot_type")))
        has_camera = sum(1 for shot in shots if str(shot.get("camera_movement", "")).strip())
        has_lighting = sum(1 for shot in shots if str(shot.get("lighting", "")).strip())
        has_atmosphere = sum(1 for shot in shots if str(shot.get("atmosphere", "")).strip())

        score = 0.0
        score += min(variety_count, 4) / 4 * 30
        score += (has_camera / len(shots)) * 25 if shots else 0
        score += (has_lighting / len(shots)) * 25 if shots else 0
        score += (has_atmosphere / len(shots)) * 20 if shots else 0

        return _clip_score(score), {
            "method": "fallback",
            "reason": str(exc)[:100],
            "variety_count": variety_count,
            "camera_coverage": round(has_camera / len(shots), 4) if shots else 0,
            "lighting_coverage": round(has_lighting / len(shots), 4) if shots else 0,
        }


def _score_stability(project_id: str, output_name: str, script: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    shots = [shot for shot in (script.get("shots", []) or []) if isinstance(shot, dict)]
    out_dir = _project_output_dir(project_id, output_name)
    final_exists = False
    clip_count = 0
    file_count = 0
    if out_dir and out_dir.exists():
        final_exists = (out_dir / "final.mp4").exists()
        clip_count = len(list(out_dir.glob("shot_*.mp4")))
        file_count = len([item for item in out_dir.rglob("*") if item.is_file()])

    records = load_trace_records(project_id, limit=50) if str(project_id or "").strip() else []
    success_count = sum(1 for item in records if str(item.get("status", "")).strip() == "success")
    trace_ratio = (success_count / len(records)) if records else 0
    produce_errors = [item for item in records if "error" in str(item.get("status", "")).strip().lower()]

    memory = get_project_memory(project_id) if str(project_id or "").strip() else {}
    reworks = memory.get("recent_reworks", []) if isinstance(memory, dict) else []
    rework_count = len(reworks)
    has_runtime_artifacts = bool(final_exists or clip_count or records or output_name)
    if not has_runtime_artifacts:
        rework_score = 0
    elif rework_count <= 1:
        rework_score = 20
    elif rework_count <= 3:
        rework_score = 15
    elif rework_count <= 5:
        rework_score = 8
    else:
        rework_score = 2

    expected_clips = len(shots)
    clip_ratio = (clip_count / expected_clips) if expected_clips else 0
    score = 0.0
    score += 35 if final_exists else 0
    score += min(clip_ratio, 1.0) * 25
    score += trace_ratio * 20
    score += rework_score

    evidence = {
        "output_dir": str(out_dir) if out_dir else "",
        "final_exists": final_exists,
        "clip_count": clip_count,
        "expected_clip_count": expected_clips,
        "file_count": file_count,
        "trace_record_count": len(records),
        "trace_success_ratio": round(trace_ratio, 4),
        "produce_error_count": len(produce_errors),
        "recent_rework_count": rework_count,
    }
    return _clip_score(score), evidence


def _grade_for_score(total_score: int) -> tuple[str, str]:
    if total_score >= 90:
        return "A", "\u76f4\u63a5\u91c7\u7528"
    if total_score >= 75:
        return "B", "\u5c0f\u5e45\u8c03\u6574\u540e\u91c7\u7528"
    if total_score >= 60:
        return "C", "\u5b9a\u5411\u8fd4\u4fee"
    return "D", "\u9700\u8981\u91cd\u505a\u6216\u91cd\u8c03\u5e93"


def _should_auto_rework(scores: dict[str, int], total_score: int, problem_types: list[str]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if total_score < AUTO_REWORK_TOTAL_SCORE_THRESHOLD:
        reasons.append(f"total_score<{AUTO_REWORK_TOTAL_SCORE_THRESHOLD}")
    low_dimensions = [key for key, value in scores.items() if int(value or 0) < AUTO_REWORK_DIMENSION_THRESHOLD]
    if low_dimensions:
        reasons.append("low_dimensions:" + ",".join(low_dimensions))
    if "aesthetic" in problem_types and int(scores.get("aesthetic", 0) or 0) < 70:
        reasons.append("aesthetic_below_70")
    return bool(reasons), reasons


def _build_auto_rework_closure(
    *,
    project_id: str,
    output_name: str,
    manual_feedback: str,
    evaluation_result: dict[str, Any],
) -> dict[str, Any]:
    scores = {
        key: int((value or {}).get("score", 0) or 0)
        for key, value in (evaluation_result.get("scores", {}) or {}).items()
        if isinstance(value, dict)
    }
    problem_types = [str(item or "").strip().lower() for item in evaluation_result.get("problem_types", []) or [] if str(item or "").strip()]
    total_score = int(evaluation_result.get("total_score", 0) or 0)
    triggered, reasons = _should_auto_rework(scores, total_score, problem_types)
    result = {
        "triggered": triggered,
        "reasons": reasons,
        "thresholds": {
            "total_score": AUTO_REWORK_TOTAL_SCORE_THRESHOLD,
            "dimension_score": AUTO_REWORK_DIMENSION_THRESHOLD,
        },
    }
    if not triggered:
        result["status"] = "skipped"
        result["message"] = "\u8bc4\u5ba1\u7ed3\u679c\u8fbe\u5230\u5f53\u524d\u95ed\u73af\u9608\u503c\uff0c\u6682\u4e0d\u81ea\u52a8\u89e6\u53d1\u8fd4\u5de5\u3002"
        return result

    closure_feedback = str(manual_feedback or "").strip()
    review_notes = evaluation_result.get("review_notes", []) or []
    if review_notes:
        closure_feedback = _text_blob(closure_feedback, *review_notes)

    try:
        from .memory import add_rework_note
        from .rework import suggest_rework

        rework_plan = suggest_rework(
            evaluation_result=evaluation_result,
            project_id=project_id,
            output_name=output_name,
            manual_feedback=closure_feedback,
        )
        note = add_rework_note(
            project_id,
            rework_plan.get("suggestion_summary", "\u81ea\u52a8\u8fd4\u5de5\u5df2\u89e6\u53d1\u3002"),
            scene_ref=output_name,
            tags=["auto_rework", rework_plan.get("problem_type", ""), rework_plan.get("suggested_task_type", "")],
            status="open",
        )
        result.update({
            "status": "triggered",
            "message": "\u8bc4\u5ba1\u4f4e\u4e8e\u9608\u503c\uff0c\u5df2\u81ea\u52a8\u751f\u6210\u8fd4\u5de5\u5efa\u8bae\u5e76\u5199\u5165\u8fd4\u5de5\u8bb0\u5f55\u3002",
            "rework_plan": rework_plan,
            "rework_note": note,
        })
        return result
    except Exception as exc:
        result.update({
            "status": "failed",
            "message": f"\u81ea\u52a8\u8fd4\u5de5\u89e6\u53d1\u5931\u8d25\uff1a{exc}",
        })
        return result


def _dimension_notes(scores: dict[str, int], manual_feedback: str) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    problem_types: list[str] = []
    if scores.get("structure", 0) < 70:
        notes.append("\u7ed3\u6784\u5206\u504f\u4f4e\uff0c\u9700\u4f18\u5148\u68c0\u67e5\u955c\u5934\u62c6\u5206\u3001\u8282\u594f\u548c\u5185\u5bb9\u5b8c\u6574\u5ea6\u3002")
        problem_types.append("structure")
    if scores.get("character", 0) < 70:
        notes.append("\u4eba\u7269\u5206\u504f\u4f4e\uff0c\u5efa\u8bae\u8865\u9f50\u89d2\u8272\u6807\u6ce8\u3001\u4eba\u8bbe\u8bb0\u5fc6\u548c\u773c\u795e\u795e\u6001\u7ea6\u675f\u3002")
        problem_types.append("character")
    if scores.get("emotion", 0) < 70:
        notes.append("\u60c5\u7eea\u5206\u504f\u4f4e\uff0c\u5efa\u8bae\u8865\u5f3a\u60c5\u7eea\u8c03\u6027\u3001\u6c14\u6c1b\u5b57\u6bb5\u548c\u60c5\u7eea\u6e10\u53d8\u7ea6\u675f\u3002")
        problem_types.append("emotion")
    if scores.get("stability", 0) < 70:
        notes.append("稳定分偏低，建议回看生成链日志、产物完整度和返工记录。")
        problem_types.append("stability")
    if scores.get("aesthetic", 0) < 70:
        notes.append("审美分偏低，镜头语言或画面质感不够高级，建议优化运镜、光影和情绪节奏描述。")
        problem_types.append("aesthetic")
    feedback = str(manual_feedback or "").strip()
    if feedback:
        notes.append(f"\u4eba\u5de5\u53cd\u9988\uff1a{feedback}")
    return notes, list(dict.fromkeys(problem_types))


def evaluate_run(
    *,
    project_id: str,
    script: dict[str, Any] | None = None,
    output_name: str = "",
    style_hint: str = "",
    context_hint: str = "",
    manual_feedback: str = "",
    preset_key: str = "",
) -> dict[str, Any]:
    normalized_project = str(project_id or "").strip()
    if not normalized_project:
        raise ValueError("project_id is required")

    script = script or {}
    structure_score, structure_evidence = _score_structure(script)
    character_score, character_evidence = _score_character(normalized_project, script, style_hint, context_hint)
    emotion_score, emotion_evidence = _score_emotion(normalized_project, script, style_hint, context_hint, preset_key)
    stability_score, stability_evidence = _score_stability(normalized_project, output_name, script)
    aesthetic_score, aesthetic_evidence = _score_aesthetic(script, style_hint, context_hint)

    scores = {
        "structure": structure_score,
        "character": character_score,
        "emotion": emotion_score,
        "stability": stability_score,
        "aesthetic": aesthetic_score,
    }
    weighted_total = sum(scores[key] * DIMENSION_WEIGHTS[key] for key in scores)
    total_score = _clip_score(weighted_total)
    grade, decision_label = _grade_for_score(total_score)
    review_notes, problem_types = _dimension_notes(scores, manual_feedback)

    sorted_dimensions = sorted(scores.items(), key=lambda item: item[1])
    weakest_dimension = sorted_dimensions[0][0]
    strongest_dimension = sorted(scores.items(), key=lambda item: item[1], reverse=True)[0][0]

    base_result = {
        "project_id": normalized_project,
        "output_name": str(output_name or "").strip(),
        "scores": {
            key: {
                "label": DIMENSION_LABELS[key],
                "score": value,
                "weight": DIMENSION_WEIGHTS[key],
            }
            for key, value in scores.items()
        },
        "total_score": total_score,
        "grade": grade,
        "decision_label": decision_label,
        "weakest_dimension": weakest_dimension,
        "strongest_dimension": strongest_dimension,
        "problem_types": problem_types,
        "review_notes": review_notes,
        "evidence": {
            "structure": structure_evidence,
            "character": character_evidence,
            "emotion": emotion_evidence,
            "stability": stability_evidence,
            "aesthetic": aesthetic_evidence,
        },
        "summary": (
            f"\u672c\u6b21\u5bfc\u6f14\u8bc4\u5ba1\u603b\u5206 {total_score}\uff0c\u7b49\u7ea7 {grade}\uff0c"
            f"\u6700\u5f31\u9879\u4e3a {DIMENSION_LABELS[weakest_dimension]}\uff0c"
            f"\u6700\u5f3a\u9879\u4e3a {DIMENSION_LABELS[strongest_dimension]}\u3002"
        ),
    }
    base_result["auto_rework"] = _build_auto_rework_closure(
        project_id=normalized_project,
        output_name=str(output_name or "").strip(),
        manual_feedback=manual_feedback,
        evaluation_result=base_result,
    )

    return base_result
