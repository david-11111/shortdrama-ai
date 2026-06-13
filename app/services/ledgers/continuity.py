"""Story continuity ledger — scene grouping, gap detection, handoff questions."""

from __future__ import annotations

import re
from typing import Any

from app.services.ledgers.models import CONTINUITY_GAP_PENALTY, ContinuityLedger, ShotAnalysis
from app.services.ledgers.shot_analysis import extract_episode_scene, group_by_scene


def build_continuity_ledger(
    project_doc: str,
    episodes_doc: str,
    scene_doc: str,
    analysis: ShotAnalysis,
    production_ledger: dict[str, Any],
) -> ContinuityLedger:
    """Build the story continuity ledger."""
    scenes = group_by_scene([], analysis)  # use analysis data directly

    # Compute scene-level data
    cursor = 0.0
    scene_goals_list: list[dict] = []
    for scene in scenes:
        duration = sum(item.duration for item in scene["shots"])
        scene["duration"] = duration
        scene["minute_range"] = _minute_range(cursor, cursor + duration)
        scene["shot_count"] = len(scene["shots"])
        scene["goal"] = _scene_goal(scene["shots"], scene_doc, episodes_doc)
        scene["first_shot_index"] = scene["shots"][0].shot_index if scene["shots"] else 0
        scene["last_shot_index"] = scene["shots"][-1].shot_index if scene["shots"] else 0
        cursor += duration
        scene_goals_list.append({
            "scene_key": scene["scene_key"],
            "goal": scene["goal"],
        })

    # Determine current scene
    current_key = _current_scene_key(scenes, analysis) or (
        str(production_ledger.get("current_scene", {}).get("scene_key") or "")
    )
    current_key = current_key or (scenes[0]["scene_key"] if scenes else "")
    current_scene = _find_scene(scenes, current_key)

    # Find gaps
    gaps = _continuity_gaps(project_doc, episodes_doc, scene_doc, analysis, scenes)
    continuity_score = max(0, 100 - len(gaps) * CONTINUITY_GAP_PENALTY)

    return ContinuityLedger(
        episode=int(current_scene.get("episode", 1)) if current_scene else 1,
        scene=int(current_scene.get("scene", 1)) if current_scene else 1,
        minute_range=current_scene.get("minute_range", "") if current_scene else "",
        previous_scene=_neighbor_scene(scenes, current_key, -1),
        current_scene=current_scene,
        next_scene=_neighbor_scene(scenes, current_key, 1),
        previous_segment=_neighbor_scene(scenes, current_key, -1),
        current_segment=current_scene,
        next_segment=_neighbor_scene(scenes, current_key, 1),
        scene_goals=scene_goals_list,
        continuity_gaps=gaps,
        handoff_questions=_handoff_questions(scenes, current_key, gaps),
        continuity_score=continuity_score,
        continuity_score_label=f"{continuity_score}分",
        character_consistency_label="已锁定" if _has_any_character_lock(analysis) else "待锁定",
        scene_bridge_label="需确认承接" if gaps else "承接稳定",
        open_question_count=len(gaps),
        next_action_label="先补承接说明" if gaps else "继续下一场规划",
        risk_label=f"{len(gaps)} 个连续性缺口" if gaps else "低",
        scenes=scenes,
    )


def _current_scene_key(scenes: list[dict], analysis: ShotAnalysis) -> str:
    """Find the first scene that still has work to do."""
    for scene in scenes:
        for item in scene["shots"]:
            if not item.has_video:
                return str(scene.get("scene_key", ""))
    return str(scenes[-1].get("scene_key", "")) if scenes else ""


def _scene_goal(shor_items: list, scene_doc: str, episodes_doc: str) -> str:
    """Extract a human-readable goal for a scene."""
    for source in (scene_doc, episodes_doc):
        for line in source.splitlines():
            clean = line.strip(" -#\t")
            if 12 <= len(clean) <= 180 and any(t in clean.lower() for t in ("goal", "目的", "冲突", "转折", "beat")):
                return clean
    for item in shor_items:
        if item.prompt_text:
            return _clip(re.sub(r"^第\s*\d+\s*集\s*第\s*\d+\s*场[，,：:\s]*", "", item.prompt_text), 140)
    return "No scene goal inferred."


def _continuity_gaps(
    project_doc: str, episodes_doc: str, scene_doc: str,
    analysis: ShotAnalysis, scenes: list[dict],
) -> list:
    """Detect continuity gaps in the project."""
    gaps = []
    if not scenes:
        gaps.append({"code": "missing_structured_shots", "reason": "No structured shots are available for continuity tracking."})
    if not scene_doc.strip():
        gaps.append({"code": "missing_scene_doc", "reason": "Current scene document is empty or unavailable."})
    if not episodes_doc.strip():
        gaps.append({"code": "missing_episode_doc", "reason": "Episode document is empty or unavailable."})
    if project_doc and scenes and len(scenes) == 1 and "第2场" in episodes_doc:
        gaps.append({"code": "scene_count_mismatch", "reason": "Episode document suggests more scenes than the current structured shot ledger covers."})
    if analysis.has_character_lock_count < analysis.total:
        gaps.append({"code": "missing_character_locks", "reason": "Some shots lack character reference locks for continuity."})
    if analysis.with_preflight < analysis.total:
        gaps.append({"code": "missing_preflight", "reason": "Some shots have no director preflight status."})
    if len(scenes) > 1:
        gaps.append({"code": "scene_handoff_check", "reason": "Confirm handoff continuity between Scene 1 and the next scene before batch generation."})
    return gaps


def _has_any_character_lock(analysis: ShotAnalysis) -> bool:
    return analysis.has_character_lock_count > 0


def _handoff_questions(scenes: list[dict], current_key: str, gaps: list) -> list[str]:
    questions = []
    current = _find_scene(scenes, current_key)
    next_scene = _neighbor_scene(scenes, current_key, 1)
    if current:
        questions.append(f"What emotional or plot state must carry out of {current.get('scene_key')}?")
    if next_scene:
        questions.append(f"What visual anchor links {current_key} to {next_scene.get('scene_key')}?")
    if gaps:
        questions.append("Which continuity gap should be resolved before the next generation batch?")
    if not questions:
        questions.append("Confirm the next scene handoff before generating more isolated shots.")
    return questions


def _find_scene(scenes: list[dict], key: str) -> dict:
    for scene in scenes:
        if scene.get("scene_key") == key:
            return dict(scene)
    return dict(scenes[0]) if scenes else {}


def _neighbor_scene(scenes: list[dict], key: str, offset: int) -> dict:
    for idx, scene in enumerate(scenes):
        if scene.get("scene_key") == key:
            target = idx + offset
            if 0 <= target < len(scenes):
                return dict(scenes[target])
    return {}


def _minute_range(start: float, end: float) -> str:
    return f"{int(start // 60) + 1}-{int(max(start, end) // 60) + 1}"


def _clip(text: str, limit: int) -> str:
    clean = str(text or "").strip()
    return clean if len(clean) <= limit else clean[:limit] + "..."


# Re-export re for _scene_goal
re = re
