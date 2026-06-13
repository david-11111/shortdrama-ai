"""Controlled executor for project-brain next actions."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any

from app.services.project_brain import build_project_brain
from app.services.project_continue_v2 import build_planning_result_v2 as _build_planning_result_v2
from app.services.project_workspace import persist_director_result_to_workspace


SUPPORTED_ACTIONS = {
    "generate_story_plan",
    "plan_scene",
    "lock_assets",
    "fix_preflight_risks",
    "plan_visual_assets",
    "plan_final_edit",
}


def continue_project_from_brain(
    project_id: str,
    *,
    action: str = "",
    instruction: str = "",
    name: str = "",
    operational_shots: list[dict[str, Any]] | None = None,
    story_understanding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before = build_project_brain(project_id, name=name, operational_shots=operational_shots)
    next_action = action.strip() or str(before.get("next_action") or "")
    if next_action not in SUPPORTED_ACTIONS:
        return {
            "project_id": project_id,
            "applied": False,
            "action": next_action,
            "message": f"Action is not executable yet: {next_action}",
            "before": before,
            "after": before,
            "writes": [],
            "shot_rows": [],
        }

    result = _build_planning_result_v2(
        project_id,
        before,
        instruction=instruction,
        name=name,
        story_understanding=story_understanding,
    )
    persisted = persist_director_result_to_workspace(
        project_id,
        result,
        source="project_brain_continue",
        reason=f"continue action: {next_action}",
        name=name,
    )
    after = build_project_brain(project_id, name=name, operational_shots=operational_shots)
    return {
        "project_id": project_id,
        "applied": True,
        "action": next_action,
        "message": "Project brain action applied.",
        "before": before,
        "after": after,
        "writes": persisted.get("writes", []),
        "shot_rows": result["shot_rows"],
        "reply": result.get("reply", ""),
        "continuity": result.get("continuity", {}),
        "intent_constraints": result.get("intent_constraints", {}),
        "story_understanding": result.get("story_understanding", {}),
    }


def _build_planning_result(project_id: str, brain: dict[str, Any], *, instruction: str, name: str) -> dict[str, Any]:
    project_name = (name or project_id).strip() or project_id
    user_intent = instruction.strip() or _infer_intent(brain, project_name)
    scale = _infer_production_scale(user_intent)
    now = datetime.now(timezone.utc).isoformat()

    continuity = {
        "character_continuity": f"{project_name} 的主角需要先锁定清晰身份、年龄段、服装、发型、情绪弧线和正脸参考；后续镜头保持同一张脸与同一套核心造型。",
        "scene_continuity": "当前先以一个可控主场景推进：空间关系明确、光线稳定、可拍建立镜头、对话镜头、反应镜头和特写。",
        "prop_continuity": "关键道具必须先写入道具表，并在相关分镜中保持外观、位置和用途一致。",
    }
    execution_plan = {
        "character_master": continuity["character_continuity"],
        "scene_master": continuity["scene_continuity"],
        "camera_plan": "先建立空间，再用双人关系镜头推进冲突，最后用特写承接情绪爆点；避免多人远景看脸。",
        "performance_beats": "每个镜头只承载一个主要动作或情绪变化，复杂调度拆成反应镜头和特写。",
    }
    reply = (
        f"## 项目启动规划 {now}\n\n"
        f"### 剧本理解\n{user_intent}\n\n"
        "### 生产规模\n"
        f"- 目标时长：约 {scale['target_duration_seconds']} 秒\n"
        f"- 预计总镜头：约 {scale['estimated_total_shots']} 个\n"
        f"- 预计场次：约 {scale['estimated_scene_count']} 场\n"
        f"- 当前落盘批次：第 1 批，{scale['initial_batch_shots']} 个分镜\n"
        f"- 原则：按需求规划全片规模，按场次批量生产；参考图全片复用，关键帧和视频分批生成。\n\n"
        "### 场次目标\n先建立一个可生成、可审查、可剪辑的核心场次：人物关系清楚，冲突点明确，场景稳定，道具可追踪。\n\n"
        "### 生产原则\n先锁定角色、场景和道具，再生成分镜；先审查分镜风险，再出关键帧；关键帧通过后再进入视频。"
    )
    shot_rows = _build_initial_batch_shots(project_name, scale, continuity, execution_plan)
    return {
        "reply": reply,
        "continuity": continuity,
        "execution_plan": execution_plan,
        "production_scale": scale,
        "shot_rows": shot_rows,
        "recommended_locks": ["character", "scene", "prop", "style"],
        "recommended_keyframe_beats": [
            {"shot_index": row["shot_index"], "beat": _beat_for_index(int(row["shot_index"]))}
            for row in shot_rows
        ],
        "quality_gate": {
            "allow_storyboard": True,
            "allow_reference_images": True,
            "allow_video_production": False,
            "reason": "已生成启动规划，但必须先补角色/场景/道具参考并审关键帧。",
        },
    }


def _infer_production_scale(instruction: str) -> dict[str, Any]:
    duration_seconds = _extract_duration_seconds(instruction) or 60
    is_long_form = duration_seconds >= 10 * 60
    avg_shot_seconds = 5 if is_long_form else 4
    estimated_total_shots = max(1, int(math.ceil(duration_seconds / avg_shot_seconds)))
    estimated_scene_count = max(1, int(math.ceil(duration_seconds / (60 if is_long_form else 30))))
    if is_long_form:
        initial_batch_shots = min(24, max(12, int(math.ceil(estimated_total_shots * 0.04))))
    else:
        initial_batch_shots = min(8, max(3, estimated_total_shots))
    return {
        "target_duration_seconds": duration_seconds,
        "estimated_total_shots": estimated_total_shots,
        "estimated_scene_count": estimated_scene_count,
        "avg_shot_seconds": avg_shot_seconds,
        "initial_batch_shots": initial_batch_shots,
        "batching_policy": "scene_batch" if is_long_form else "single_scene",
        "scale_note": "长剧按全片规模规划，按场次批量落盘和生成。" if is_long_form else "短内容可在一个核心场次内完成首批生产。",
    }


def _extract_duration_seconds(text: str) -> int | None:
    compact = str(text or "")
    patterns = [
        (r"(\d+(?:\.\d+)?)\s*(?:分钟|分|min|mins|minute|minutes)", 60),
        (r"(\d+(?:\.\d+)?)\s*(?:小时|h|hour|hours)", 3600),
        (r"(\d+(?:\.\d+)?)\s*(?:秒|s|sec|secs|second|seconds)", 1),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            return max(1, int(float(match.group(1)) * multiplier))
    return None


def _build_initial_batch_shots(
    project_name: str,
    scale: dict[str, Any],
    continuity: dict[str, str],
    execution_plan: dict[str, str],
) -> list[dict[str, Any]]:
    raise RuntimeError("Legacy template storyboard generation is disabled; use project_continue_v2.")


def _beat_for_index(index: int) -> str:
    beats = [
        "建立空间与主角身份",
        "推进人物关系和冲突",
        "捕捉主角反应",
        "锁定道具或证据",
        "推进动作",
        "强化情绪压力",
        "形成反打关系",
        "给出转场落点",
    ]
    return beats[(index - 1) % len(beats)]


def _infer_intent(brain: dict[str, Any], project_name: str) -> str:
    context = brain.get("context") if isinstance(brain.get("context"), dict) else {}
    project_context = str(context.get("project") or "").strip()
    if project_context:
        return f"围绕《{project_name}》制作精品短剧，当前要先把剧本理解、人物关系、核心冲突和第一场生产路径落定。"
    return f"围绕《{project_name}》建立精品短剧项目的第一场规划。"
