"""Project startup brain for file-backed short-drama workspaces."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.services.project_brain_ledgers import (
    build_director_ledgers,
    director_ledger_missing_items,
    director_ledger_risks,
    director_ledger_signals,
)
from app.services.project_workspace import read_project_workspace


WORKFLOW_STAGES = [
    "script_understanding",
    "episode_scene_planning",
    "asset_locking",
    "storyboard_directing",
    "preflight_review",
    "keyframe_generation",
    "video_generation",
    "video_review",
    "final_edit",
]

EXECUTABLE_NEXT_ACTIONS = {
    "generate_story_plan",
    "plan_scene",
    "lock_assets",
    "generate_storyboard",
    "plan_visual_assets",
    "generate_keyframes",
    "generate_videos",
    "plan_final_edit",
}

CONTEXT_SOURCE_SPECS = {
    "PROJECT.md": {
        "role": "project_brief",
        "label": "项目总纲",
        "used_by": ["story_plan", "target_duration", "production_ledger"],
        "impact_if_missing": "无法可靠判断项目主题、目标时长和商业交付边界。",
    },
    "story/characters.md": {
        "role": "character_memory",
        "label": "角色锁定",
        "used_by": ["character_lock", "asset_reuse", "prompt_continuity"],
        "impact_if_missing": "角色脸、服装、身份和关系无法稳定复用。",
    },
    "story/episodes.md": {
        "role": "episode_plan",
        "label": "剧集结构",
        "used_by": ["scene_order", "story_continuity", "production_ledger"],
        "impact_if_missing": "无法确认当前场属于哪一集、前后场如何承接。",
    },
    "scenes/episode-01-scene-01.md": {
        "role": "scene_plan",
        "label": "当前场计划",
        "used_by": ["current_scene", "shot_strategy", "continuity_bridge"],
        "impact_if_missing": "无法定位当前场目标、冲突、情绪和下一场承接。",
    },
    "shots/episode-01-scene-01.json": {
        "role": "shot_plan",
        "label": "分镜清单",
        "used_by": ["shot_count", "preflight", "keyframe_queue", "video_queue"],
        "impact_if_missing": "无法知道要生成哪些镜头，也无法派发关键帧或视频任务。",
    },
    "memory/decisions.md": {
        "role": "decision_memory",
        "label": "历史决策",
        "used_by": ["decision_count", "avoid_repeat_work", "operator_audit"],
        "impact_if_missing": "无法追溯过去为什么这么做，容易重复决策。",
    },
    "memory/failures.md": {
        "role": "failure_memory",
        "label": "失败经验",
        "used_by": ["risk_detection", "retry_guardrail", "failure_count"],
        "impact_if_missing": "无法把失败经验带入下一轮风控。",
    },
    "memory/constraints.md": {
        "role": "constraint_memory",
        "label": "约束规则",
        "used_by": ["cost_guardrail", "style_constraints", "commercial_safety"],
        "impact_if_missing": "无法稳定执行预算、风格、安全和商业化约束。",
    },
}

EMPTY_FIELD_LABELS = {
    "姓名",
    "年龄",
    "身份",
    "外貌锚点",
    "性格锚点",
    "情绪弧线",
    "参考资产",
    "场景地点",
    "出场角色",
    "情绪目标",
    "冲突点",
    "剧情功能",
    "建立镜头",
    "对话镜头",
    "反应镜头",
    "特写",
    "情绪爆点",
    "转场",
    "故事一句话",
    "核心冲突",
    "分集规划",
    "第 1 集",
    "本集目标",
    "情绪推进",
    "关键反转",
    "主要场次",
    "场次目标",
    "剧本正文",
    "分镜导演要求",
    "主角",
    "重要角色",
}

PLACEHOLDER_FRAGMENTS = (
    "待填写",
    "????",
    "TODO",
    "FIXME",
    "placeholder",
    "需要先锁定",
    "必须先补",
    "先补角色",
    "未锁定",
    "待记录",
    "每个角色都需要记录",
    "角色表 -",
    "剧集规划 -",
    "第 1 集 第 1 场 -",
)

DOC_MARKER_FRAGMENTS = (
    "Director Plan",
    "Story / Production Draft",
    "Director Scene Plan",
    "Director Lock",
    "Character Continuity",
    "Scene Continuity",
    "Prop Continuity",
    "Shot Summary",
    "项目启动规划",
)


CONTENT_SIGNAL_SPECS = {
    "has_director_plan": (("Director Plan", "Story / Production Draft", "Director Scene Plan"), 20, ""),
    "has_character_lock": (("Director Lock", "Character Continuity"), 5, "Character Continuity"),
    "has_scene_plan": (("Director Scene Plan", "Shot Summary"), 24, ""),
}


GENERATION_ACTIONS = ("generate_keyframes", "generate_videos")
DOWNSTREAM_ACTIONS = (*GENERATION_ACTIONS, "plan_final_edit")


SAFETY_GATE_SPECS = (
    {"id": "workspace_ready", "label": "Workspace files are readable", "ok": "workspace_ready", "reason": "Required workspace bootstrap files are missing or unreadable.", "for": ("generate_story_plan", "plan_scene", "lock_assets", "plan_visual_assets", *DOWNSTREAM_ACTIONS), "evidence": ("read_file_count", "required_file_count")},
    {"id": "story_plan_ready", "label": "Story plan contains substantive content", "ok": "has_director_plan", "reason": "Story/episode plan only contains placeholders, markers, or empty fields.", "for": ("plan_scene", "lock_assets", "plan_visual_assets", *DOWNSTREAM_ACTIONS), "evidence": ("has_director_plan",)},
    {"id": "scene_plan_ready", "label": "Current scene plan contains substantive content", "ok": "has_scene_plan", "reason": "Scene plan is missing substantive location, role, conflict, or shot-summary content.", "for": ("lock_assets", "plan_visual_assets", *DOWNSTREAM_ACTIONS), "evidence": ("has_scene_plan",)},
    {"id": "asset_locks_ready", "label": "Reusable character/asset locks exist", "ok": "has_character_lock", "reason": "Character continuity is not materially locked; downstream generation may drift or fabricate identities.", "for": DOWNSTREAM_ACTIONS, "evidence": ("has_character_lock", "ledger_locked_asset_count", "ledger_reusable_asset_count")},
    {"id": "shot_plan_ready", "label": "Structured shots exist", "ok": "has_shots", "reason": "No structured shot rows are available for preflight or generation.", "for": ("plan_visual_assets", *DOWNSTREAM_ACTIONS), "evidence": ("workspace_shot_count", "operational_shot_count")},
    {"id": "preflight_clear", "label": "No blocked preflight risks", "ok": "no_blocked_risks", "reason": "Blocked preflight risks must be resolved before generation.", "for": GENERATION_ACTIONS, "evidence": ("blocked_risk_count",)},
    {"id": "visual_budget_guard", "code": "visual_budget_clear", "label": "Visual generation budget is bounded", "ok": "visual_budget_ok", "reason": "Estimated Seedream image demand is over budget; plan reusable visual assets first.", "for": ("generate_keyframes",), "evidence": ("seedream_budget_level", "seedream_estimated_image_count", "seedream_avoided_image_count"), "severity": "warning"},
    {"id": "active_generation_guard", "label": "No duplicate generation is already active", "ok": "no_active_generation", "reason": "A keyframe or video generation task is already active; wait for writeback before dispatching more.", "for": GENERATION_ACTIONS, "evidence": ("operational_generating_count", "operational_generating_keyframe_count", "operational_generating_video_count"), "severity": "warning"},
)


def build_project_brain(
    project_id: str,
    *,
    name: str = "",
    goal: str = "",
    operational_shots: list[dict[str, Any]] | None = None,
    final_edit_plan: dict[str, Any] | None = None,
    visual_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace = read_project_workspace(project_id, name=name)
    bootstrap = workspace.get("bootstrap") if isinstance(workspace.get("bootstrap"), dict) else {}
    files = workspace.get("files") if isinstance(workspace.get("files"), list) else []

    project_doc = _text(bootstrap.get("PROJECT.md"))
    characters_doc = _text(bootstrap.get("story/characters.md"))
    episodes_doc = _text(bootstrap.get("story/episodes.md"))
    scene_doc = _text(bootstrap.get("scenes/episode-01-scene-01.md"))
    decisions_doc = _text(bootstrap.get("memory/decisions.md"))
    failures_doc = _text(bootstrap.get("memory/failures.md"))
    constraints_doc = _text(bootstrap.get("memory/constraints.md"))
    shots_payload = _parse_json(bootstrap.get("shots/episode-01-scene-01.json"))
    workspace_shots = shots_payload.get("shots") if isinstance(shots_payload.get("shots"), list) else []
    op_shots = operational_shots if isinstance(operational_shots, list) else []
    edit_clips = (
        final_edit_plan.get("clips")
        if isinstance(final_edit_plan, dict) and isinstance(final_edit_plan.get("clips"), list)
        else []
    )
    edit_settings = final_edit_plan.get("settings") if isinstance(final_edit_plan, dict) and isinstance(final_edit_plan.get("settings"), dict) else {}
    preview_export = edit_settings.get("preview_export") if isinstance(edit_settings.get("preview_export"), dict) else {}
    final_export = edit_settings.get("final_export") if isinstance(edit_settings.get("final_export"), dict) else {}
    final_delivery_report = edit_settings.get("final_delivery_report") if isinstance(edit_settings.get("final_delivery_report"), dict) else {}
    visual_budget = _visual_budget(visual_plan, op_shots)
    production_ledger = _build_production_ledger(
        project_doc=project_doc,
        episodes_doc=episodes_doc,
        scene_doc=scene_doc,
        workspace_shots=workspace_shots,
        operational_shots=op_shots,
    )
    director_ledgers = build_director_ledgers(
        project_doc=project_doc,
        episodes_doc=episodes_doc,
        scene_doc=scene_doc,
        workspace_shots=workspace_shots,
        operational_shots=op_shots,
        final_edit_plan=final_edit_plan,
        visual_budget=visual_budget,
        production_ledger=production_ledger,
    )
    content_signals = _build_content_signals(
        episodes_doc=episodes_doc,
        scene_doc=scene_doc,
        characters_doc=characters_doc,
    )

    signals = {
        "workspace_ready": bool(workspace.get("ready")),
        "read_file_count": sum(1 for item in files if item.get("exists")),
        "required_file_count": len(files),
        **content_signals,
        "workspace_shot_count": len(workspace_shots),
        "operational_shot_count": len(op_shots),
        "operational_generating_count": _count_generating(op_shots),
        "operational_generating_keyframe_count": _count_generating_keyframes(op_shots),
        "operational_generating_video_count": _count_generating_videos(op_shots),
        "operational_pending_keyframe_count": _count_pending_keyframes(op_shots),
        "operational_image_done_count": _count_image_done(op_shots),
        "operational_pending_video_count": _count_pending_videos(op_shots),
        "operational_video_done_count": _count_video_done(op_shots),
        "visual_plan_action_count": visual_budget["action_count"],
        "visual_bind_existing_count": visual_budget["bind_existing_count"],
        "visual_reference_generation_count": visual_budget["generate_reference_count"],
        "seedream_estimated_image_count": visual_budget["estimated_seedream_images"],
        "seedream_pending_keyframe_count": visual_budget["pending_keyframes"],
        "seedream_budget_level": visual_budget["budget_level"],
        "seedream_reuse_ratio_percent": visual_budget["reuse_ratio_percent"],
        "seedream_avoided_image_count": visual_budget["avoided_seedream_images"],
        "seedream_estimated_without_reuse": visual_budget["estimated_without_reuse"],
        "final_edit_plan_ready": bool(edit_clips),
        "final_edit_clip_count": len(edit_clips),
        "preview_export_ready": bool(preview_export.get("url")),
        "preview_export_task_id": str(preview_export.get("task_id") or ""),
        "final_export_ready": bool(final_export.get("url")),
        "final_export_task_id": str(final_export.get("task_id") or ""),
        "final_delivery_passed": bool(final_delivery_report.get("passed")),
        "ledger_target_total_seconds": production_ledger["target_total_seconds"],
        "ledger_planned_duration_seconds": production_ledger["planned_duration_seconds"],
        "ledger_generated_video_seconds": production_ledger["generated_video_seconds"],
        "ledger_remaining_seconds": production_ledger["remaining_seconds"],
        "ledger_completion_percent": production_ledger["completion_percent"],
        "ledger_scene_count": len(production_ledger["scenes"]),
        "ledger_current_scene_key": production_ledger["current_scene"].get("scene_key", ""),
        "ledger_locked_asset_count": production_ledger["asset_locks"]["locked_total"],
        "ledger_reusable_asset_count": production_ledger["asset_locks"]["reusable_total"],
        "decision_count": decisions_doc.count("\n- path:"),
        "failure_count": failures_doc.count("\n- path:") + failures_doc.lower().count("error"),
        "constraint_chars": len(constraints_doc),
    }
    signals.update(director_ledger_signals(director_ledgers))
    risks = _collect_risks(workspace_shots, op_shots)
    risks.extend(_collect_visual_budget_risks(visual_budget))
    risks.extend(director_ledger_risks(director_ledgers))
    missing = _collect_missing(signals, risks)
    missing.extend(director_ledger_missing_items(director_ledgers))
    phase, next_action = _decide_phase(signals, risks)
    safety_gates = _build_safety_gates(signals=signals, risks=risks, next_action=next_action)
    summary = _build_summary(phase, signals, risks, missing)
    context_coverage = _build_context_coverage(
        files=files,
        bootstrap=bootstrap,
        shots_payload=shots_payload,
        signals=signals,
    )
    ledger_merge_audit = _build_ledger_merge_audit(
        signals=signals,
        director_ledgers=director_ledgers,
        production_ledger=production_ledger,
        visual_budget=visual_budget,
        phase=phase,
        next_action=next_action,
        risks=risks,
        missing=missing,
    )
    creative_lowering_audit = _build_creative_lowering_audit(
        workspace_shots=workspace_shots,
        operational_shots=op_shots,
        final_edit_plan=final_edit_plan,
        director_ledgers=director_ledgers,
    )
    continuity_handoff_audit = _build_continuity_handoff_audit(
        continuity_ledger=director_ledgers["story_continuity_ledger"],
        production_ledger=production_ledger,
        signals=signals,
        phase=phase,
        next_action=next_action,
    )
    cost_control_audit = _build_cost_control_audit(
        cost_ledger=director_ledgers["cost_risk_ledger"],
        visual_budget=visual_budget,
        signals=signals,
        risks=risks,
        phase=phase,
        next_action=next_action,
    )
    final_delivery_audit = _build_final_delivery_audit(
        operational_shots=op_shots,
        workspace_shots=workspace_shots,
        final_edit_plan=final_edit_plan,
        final_quality_ledger=director_ledgers["final_quality_ledger"],
        signals=signals,
        phase=phase,
        next_action=next_action,
    )
    feedback_loop_audit = _build_feedback_loop_audit(
        operational_shots=op_shots,
        workspace_shots=workspace_shots,
        final_edit_plan=final_edit_plan,
        decisions_doc=decisions_doc,
        failures_doc=failures_doc,
        signals=signals,
        phase=phase,
        next_action=next_action,
    )

    return {
        "project_id": project_id,
        "brain_version": "project_brain_v1",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "stage_index": WORKFLOW_STAGES.index(phase) if phase in WORKFLOW_STAGES else 0,
        "goal": goal,  # 用户原始意图，供前端显示
        "summary": summary,
        "next_action": next_action,
        "next_action_label": _next_action_label(next_action),
        "can_continue": next_action in EXECUTABLE_NEXT_ACTIONS,
        "missing": missing,
        "risks": risks,
        "safety_gates": safety_gates,
        "signals": signals,
        "read_files": context_coverage,
        "context": {
            "project": _excerpt(project_doc, 500),
            "characters": _excerpt(characters_doc, 700),
            "episodes": _excerpt(episodes_doc, 700),
            "scene": _excerpt(scene_doc, 900),
            "decisions": _excerpt(decisions_doc, 700),
            "failures": _excerpt(failures_doc, 500),
            "constraints": _excerpt(constraints_doc, 700),
            "shots": workspace_shots[:20],
            "visual_budget": visual_budget,
            "production_ledger": production_ledger,
            "creative_technique_ledger": director_ledgers["creative_technique_ledger"],
            "story_continuity_ledger": director_ledgers["story_continuity_ledger"],
            "cost_risk_ledger": director_ledgers["cost_risk_ledger"],
            "final_quality_ledger": director_ledgers["final_quality_ledger"],
            "context_coverage": context_coverage,
            "ledger_merge_audit": ledger_merge_audit,
            "creative_lowering_audit": creative_lowering_audit,
            "continuity_handoff_audit": continuity_handoff_audit,
            "cost_control_audit": cost_control_audit,
            "final_delivery_audit": final_delivery_audit,
            "feedback_loop_audit": feedback_loop_audit,
            "safety_gates": safety_gates,
        },
    }


def _text(value: Any) -> str:
    return str(value or "")


def _parse_json(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_context_coverage(
    *,
    files: list[Any],
    bootstrap: dict[str, Any],
    shots_payload: dict[str, Any],
    signals: dict[str, Any],
) -> list[dict[str, Any]]:
    file_map = {
        str(item.get("path") or ""): item
        for item in files
        if isinstance(item, dict)
    }
    rows: list[dict[str, Any]] = []
    for path, spec in CONTEXT_SOURCE_SPECS.items():
        file_meta = file_map.get(path, {})
        exists = bool(file_meta.get("exists"))
        raw = _text(bootstrap.get(path))
        parsed, parse_status, item_count = _context_parse_status(path, raw, shots_payload)
        consumed = _context_consumed(path, signals, parsed=parsed, item_count=item_count)
        rows.append({
            "path": path,
            "exists": exists,
            "size": int(file_meta.get("size") or 0),
            "role": spec["role"],
            "label": spec["label"],
            "used_by": list(spec["used_by"]),
            "impact_if_missing": spec["impact_if_missing"],
            "chars": len(raw),
            "parsed": parsed,
            "parse_status": parse_status,
            "item_count": item_count,
            "consumed": consumed,
            "coverage": "covered" if exists and parsed and consumed else "partial" if exists else "missing",
        })
    return rows


def _context_parse_status(path: str, raw: str, shots_payload: dict[str, Any]) -> tuple[bool, str, int]:
    if path.endswith(".json"):
        if not raw.strip():
            return False, "empty_json", 0
        if not isinstance(shots_payload, dict) or not shots_payload:
            return False, "invalid_json", 0
        shots = shots_payload.get("shots") if isinstance(shots_payload.get("shots"), list) else []
        return True, "json_ok", len(shots)
    if not raw.strip():
        return False, "empty_text", 0
    meaningful_lines = [
        line for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("<!--")
    ]
    return True, "text_ok", len(meaningful_lines)


def _context_consumed(path: str, signals: dict[str, Any], *, parsed: bool, item_count: int) -> bool:
    if not parsed:
        return False
    if path == "PROJECT.md":
        return True
    if path == "story/characters.md":
        return bool(signals.get("has_character_lock"))
    if path == "story/episodes.md":
        return bool(signals.get("has_director_plan")) or int(signals.get("ledger_scene_count") or 0) > 0
    if path == "scenes/episode-01-scene-01.md":
        return bool(signals.get("has_scene_plan")) or bool(signals.get("has_director_plan"))
    if path == "shots/episode-01-scene-01.json":
        return item_count > 0 or int(signals.get("workspace_shot_count") or 0) > 0
    if path == "memory/decisions.md":
        return int(signals.get("decision_count") or 0) > 0 or parsed
    if path == "memory/failures.md":
        return int(signals.get("failure_count") or 0) > 0 or parsed
    if path == "memory/constraints.md":
        return int(signals.get("constraint_chars") or 0) > 0
    return parsed


def _build_ledger_merge_audit(
    *,
    signals: dict[str, Any],
    director_ledgers: dict[str, Any],
    production_ledger: dict[str, Any],
    visual_budget: dict[str, Any],
    phase: str,
    next_action: str,
    risks: list[dict[str, Any]],
    missing: list[dict[str, str]],
) -> list[dict[str, Any]]:
    cost = director_ledgers.get("cost_risk_ledger") if isinstance(director_ledgers.get("cost_risk_ledger"), dict) else {}
    quality = director_ledgers.get("final_quality_ledger") if isinstance(director_ledgers.get("final_quality_ledger"), dict) else {}
    continuity = director_ledgers.get("story_continuity_ledger") if isinstance(director_ledgers.get("story_continuity_ledger"), dict) else {}
    creative = director_ledgers.get("creative_technique_ledger") if isinstance(director_ledgers.get("creative_technique_ledger"), dict) else {}
    asset_locks = production_ledger.get("asset_locks") if isinstance(production_ledger.get("asset_locks"), dict) else {}
    missing_codes = {str(item.get("code") or "") for item in missing}
    risk_codes = {str(item.get("code") or "") for item in risks}

    def row(
        component: str,
        label: str,
        present: bool,
        evidence: str,
        signals_used: list[str],
        consumed_by: list[str],
        decision_effect: str,
    ) -> dict[str, Any]:
        return {
            "component": component,
            "label": label,
            "present": bool(present),
            "evidence": evidence,
            "signals_used": signals_used,
            "consumed_by": consumed_by,
            "decision_effect": decision_effect,
            "coverage": "covered" if present and consumed_by else "partial" if present else "missing",
        }

    rows = [
        row(
            "production_ledger",
            "进度账本",
            bool(production_ledger.get("scenes") or production_ledger.get("planned_duration_seconds")),
            (
                f"scene_count={signals.get('ledger_scene_count')}; "
                f"current={signals.get('ledger_current_scene_key') or '-'}; "
                f"generated={signals.get('ledger_generated_video_seconds')}s; "
                f"remaining={signals.get('ledger_remaining_seconds')}s"
            ),
            [
                "ledger_scene_count",
                "ledger_current_scene_key",
                "ledger_generated_video_seconds",
                "ledger_remaining_seconds",
                "ledger_completion_percent",
            ],
            ["summary", "video_generation", "final_edit"] if production_ledger.get("scenes") else [],
            f"当前 phase={phase}, next_action={next_action} 会引用进度账本判断生成/剪辑阶段。",
        ),
        row(
            "character_lock",
            "角色锁定",
            bool(signals.get("has_character_lock")),
            f"has_character_lock={signals.get('has_character_lock')}; locked_total={signals.get('ledger_locked_asset_count')}",
            ["has_character_lock", "ledger_locked_asset_count"],
            ["missing", "phase", "next_action"] if signals.get("has_character_lock") or "asset_locks" in missing_codes else ["missing", "phase"],
            "未锁定时 _decide_phase 会停在 asset_locking/lock_assets；已锁定后允许进入分镜/生成。",
        ),
        row(
            "scene_lock",
            "场景锁定",
            bool(signals.get("has_scene_plan")),
            f"has_scene_plan={signals.get('has_scene_plan')}; continuity_gaps={signals.get('continuity_gap_count')}",
            ["has_scene_plan", "continuity_gap_count", "continuity_handoff_question_count"],
            ["missing", "phase", "next_action", "story_continuity_ledger"],
            "未写入当前场计划时 _decide_phase 会停在 episode_scene_planning/plan_scene。",
        ),
        row(
            "asset_reuse",
            "资产复用",
            bool(signals.get("ledger_reusable_asset_count") or signals.get("visual_bind_existing_count") or signals.get("visual_plan_action_count")),
            (
                f"reusable={signals.get('ledger_reusable_asset_count')}; "
                f"bind_existing={signals.get('visual_bind_existing_count')}; "
                f"avoided_seedream={signals.get('seedream_avoided_image_count')}; "
                f"budget={signals.get('seedream_budget_level')}"
            ),
            [
                "ledger_reusable_asset_count",
                "visual_plan_action_count",
                "visual_bind_existing_count",
                "seedream_budget_level",
                "seedream_avoided_image_count",
            ],
            ["phase", "next_action", "risks", "cost_risk_ledger"] if signals.get("visual_plan_action_count") or signals.get("seedream_budget_level") == "over_budget" else ["cost_risk_ledger"],
            "有视觉资产规划或预算超限时，会优先进入 plan_visual_assets，避免直接批量关键帧。",
        ),
        row(
            "creative_ledger",
            "创作技巧账本",
            bool(creative),
            f"applied={signals.get('creative_applied_technique_count')}; candidate={signals.get('creative_candidate_technique_count')}; missing_stage={signals.get('creative_missing_stage_count')}",
            [
                "creative_applied_technique_count",
                "creative_candidate_technique_count",
                "creative_missing_stage_count",
            ],
            ["missing"] if "creative_technique_coverage" in missing_codes else [],
            "当前会进入 missing 提醒；是否阻断生成还未收紧，属于调试期 partial/covered 之间的观察项。",
        ),
        row(
            "quality_ledger",
            "成片验收账本",
            bool(quality),
            f"ready_score={signals.get('final_quality_ready_score')}; blockers={signals.get('final_quality_blocking_count')}",
            ["final_quality_ready_score", "final_quality_blocking_count"],
            ["risks", "missing", "final_edit"] if "final_quality_blockers" in missing_codes or "final_quality_blockers" in risk_codes else ["final_edit"],
            "出现成片阻塞项时会进入 risks/missing；有视频后影响 plan_final_edit/open_final_cut。",
        ),
        row(
            "decision_memory",
            "历史决策记忆",
            int(signals.get("decision_count") or 0) > 0,
            f"decision_count={signals.get('decision_count')}",
            ["decision_count"],
            ["audit"],
            "目前主要用于审计展示，尚未深度影响 next_action，标记为 partial。",
        ),
        row(
            "failure_memory",
            "失败经验记忆",
            int(signals.get("failure_count") or 0) > 0,
            f"failure_count={signals.get('failure_count')}",
            ["failure_count"],
            ["audit"],
            "目前主要用于信号统计，后续应进入 retry_guardrail。",
        ),
        row(
            "constraint_memory",
            "约束规则记忆",
            int(signals.get("constraint_chars") or 0) > 0,
            f"constraint_chars={signals.get('constraint_chars')}",
            ["constraint_chars"],
            ["audit"],
            "目前主要确认约束存在，后续应进入成本、风格和商业安全硬约束。",
        ),
    ]

    if cost:
        rows.append(row(
            "cost_ledger",
            "成本风控账本",
            True,
            f"risk_level={cost.get('risk_level')}; pending={cost.get('pending_operation_count')}; visual_budget={visual_budget.get('budget_level')}",
            ["cost_risk_level", "remaining_image_operations", "remaining_video_operations"],
            ["risks", "next_action", "plan_visual_assets"] if cost.get("risk_level") in {"watch", "high"} else ["summary"],
            "成本风险为 watch/high 时进入 risks；视觉预算过高时阻止直接批量生成。",
        ))
    return rows


def _build_creative_lowering_audit(
    *,
    workspace_shots: list[Any],
    operational_shots: list[dict[str, Any]],
    final_edit_plan: dict[str, Any] | None,
    director_ledgers: dict[str, Any],
) -> list[dict[str, Any]]:
    shots = _merge_shot_rows_for_audit(workspace_shots, operational_shots)
    final_edit_plan = final_edit_plan if isinstance(final_edit_plan, dict) else {}
    clips = final_edit_plan.get("clips") if isinstance(final_edit_plan.get("clips"), list) else []
    creative = director_ledgers.get("creative_technique_ledger") if isinstance(director_ledgers.get("creative_technique_ledger"), dict) else {}
    applied_by_stage = creative.get("applied") if isinstance(creative.get("applied"), dict) else {}
    candidate_by_stage = creative.get("candidate") if isinstance(creative.get("candidate"), dict) else {}

    prompt_shots = [shot for shot in shots if _shot_text_for_audit(shot)]
    image_boundary_shots = [
        shot for shot in prompt_shots
        if _has_image_boundary_signal(shot) or _status(shot) in {"pending", "queued", "generating_image", "image_done"}
    ]
    video_boundary_shots = [
        shot for shot in prompt_shots
        if shot.get("selected_image") or shot.get("selected_video") or _status(shot) in {"generating_video", "video_done", "done"}
    ]
    voice_candidate_shots = [shot for shot in shots if _has_voice_text_for_audit(shot)]
    voice_applied_shots = [shot for shot in voice_candidate_shots if _has_voice_payload_for_audit(shot)]
    recipe_id = (
        final_edit_plan.get("recipe_id")
        or (final_edit_plan.get("settings") if isinstance(final_edit_plan.get("settings"), dict) else {}).get("recipe_id")
    )

    def row(
        component: str,
        label: str,
        candidate_count: int,
        applied_count: int,
        lowered_to: list[str],
        execution_boundary: str,
        evidence: str,
        gap: str,
        *,
        code_boundary: bool = False,
        examples: list[str] | None = None,
    ) -> dict[str, Any]:
        if candidate_count <= 0:
            coverage = "missing"
        elif applied_count >= candidate_count:
            coverage = "covered"
        elif applied_count > 0 or code_boundary:
            coverage = "partial"
        else:
            coverage = "missing"
        return {
            "component": component,
            "label": label,
            "candidate_count": int(candidate_count),
            "applied_count": int(applied_count),
            "lowered_to": lowered_to,
            "execution_boundary": execution_boundary,
            "evidence": evidence,
            "coverage": coverage,
            "gap": "" if coverage == "covered" else gap,
            "code_boundary": bool(code_boundary),
            "examples": examples or [],
        }

    matched_applied = sum(1 for shot in shots if _as_list_for_audit(shot.get("matched_libraries")))
    visual_marker_applied = sum(1 for shot in image_boundary_shots if _has_visual_marker_for_audit(shot))
    image_executed = sum(1 for shot in image_boundary_shots if shot.get("selected_image") or _status(shot) in {"generating_image", "image_done"})
    video_executed = sum(1 for shot in video_boundary_shots if shot.get("selected_video") or _status(shot) in {"generating_video", "video_done", "done"})
    final_cut_candidates = len(clips) or sum(1 for shot in shots if shot.get("selected_video"))
    final_cut_applied = len(clips) if recipe_id else 0

    return [
        row(
            "matched_libraries",
            "剪辑技巧库匹配",
            len(prompt_shots),
            matched_applied,
            ["shot.matched_libraries", "creative_technique_ledger.per_shot"],
            "director_chat_engine / prompt_compiler",
            _audit_evidence("matched", matched_applied, len(prompt_shots), _examples_for_audit(shots, "matched_libraries")),
            "有分镜文本但未写入 matched_libraries 时，只能说明技巧候选存在，不能证明被映射到具体镜头。",
            examples=_examples_for_audit(shots, "matched_libraries"),
        ),
        row(
            "visual_quality_rules",
            "光影/景深/去AI感规则",
            len(image_boundary_shots),
            max(visual_marker_applied, image_executed),
            ["Seedream image prompt", "Seedance video prompt", "ref_resolver.build_image_generation_payload"],
            "ref_resolver -> apply_visual_quality_controls",
            f"prompt_shots={len(prompt_shots)}; image_boundary={len(image_boundary_shots)}; selected_or_generating_image={image_executed}; persisted_markers={visual_marker_applied}",
            "规则已接在生成 payload 边界；但当前镜头未实际进入图片生成或未持久化 payload 时，只能判定为 partial。",
            code_boundary=True,
            examples=_examples_for_audit(image_boundary_shots, "prompt"),
        ),
        row(
            "human_performance_controls",
            "微表情/肢体联动规则",
            len(image_boundary_shots),
            image_executed,
            ["Seedream image prompt", "Seedance video prompt", "visual_quality_rules.build_human_performance_controls"],
            "ref_resolver -> apply_visual_quality_controls",
            f"真人表演控制随 visual_quality_rules 一起注入；selected_or_generating_image={image_executed}",
            "没有实际生成到图片/视频边界前，不能证明人物表演细节已经被供应商执行。",
            code_boundary=True,
            examples=_examples_for_audit(image_boundary_shots, "prompt"),
        ),
        row(
            "video_motion_controls",
            "视频运镜规则",
            len(video_boundary_shots),
            video_executed,
            ["Seedance video prompt", "ref_resolver.build_video_generation_payload"],
            "ref_resolver -> apply_video_motion_controls",
            f"selected_image_or_video_ready={len(video_boundary_shots)}; selected_or_generating_video={video_executed}",
            "需要镜头具备 selected_image 并进入视频生成边界，运镜规则才算真正下沉到 Seedance payload。",
            code_boundary=True,
            examples=_examples_for_audit(video_boundary_shots, "prompt"),
        ),
        row(
            "voice_delivery_rules",
            "配音节奏/停顿/发声状态",
            len(voice_candidate_shots),
            len(voice_applied_shots),
            ["TTS payload.text", "TTS payload.speed", "TTS payload.volume", "TTS payload.delivery_profile"],
            "tts.prepare_tts_payload -> voice_delivery_rules.prepare_tts_payload",
            f"voice_text_shots={len(voice_candidate_shots)}; tts_payload_or_audio={len(voice_applied_shots)}",
            "有台词/旁白但未生成 TTS payload 或音频时，只能说明配音规则候选存在。",
            code_boundary=True,
            examples=_examples_for_audit(voice_candidate_shots, "voiceover"),
        ),
        row(
            "final_cut_recipes",
            "剪辑步骤/成片配方",
            final_cut_candidates,
            final_cut_applied,
            ["final_edit_plan.recipe_id", "final_edit_plan.settings.recipe_id", "final_cut_rule_apply"],
            "final_cut_ai / final_cut_rule_apply",
            f"clips={len(clips)}; selected_video_count={sum(1 for shot in shots if shot.get('selected_video'))}; recipe_id={recipe_id or '-'}",
            "已有视频或剪辑片段但未绑定 recipe_id 时，FFmpeg 只会按基础方案剪，不算技巧步骤落地。",
            code_boundary=bool(final_cut_candidates),
            examples=[str(recipe_id)] if recipe_id else [],
        ),
        row(
            "content_humanizer",
            "文案去AI味/改写强度",
            sum(len(values) for values in candidate_by_stage.values() if isinstance(values, list) and "content_humanizer" in values) or len(prompt_shots),
            sum(len(values) for values in applied_by_stage.values() if isinstance(values, list) and "content_humanizer" in values),
            ["script rewrite layer", "shot.prompt_revision", "content_humanizer marker"],
            "content_humanizer.humanize_generated_copy",
            "当前按分镜/账本 marker 统计，未检测到 marker 不代表函数不存在。",
            "需要在写剧本、改剧本、分镜改写时持久化 content_humanizer/prompt_revision，才能审计改写强度。",
            code_boundary=True,
            examples=_examples_for_audit(shots, "content_humanizer"),
        ),
    ]


def _merge_shot_rows_for_audit(workspace_shots: list[Any], operational_shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_index: dict[int, dict[str, Any]] = {}
    overflow = 10_000
    for source in (workspace_shots, operational_shots):
        for item in source:
            if not isinstance(item, dict):
                continue
            index = int(item.get("shot_index") or item.get("index") or 0)
            if index <= 0:
                index = overflow
                overflow += 1
            by_index[index] = {**by_index.get(index, {}), **item}
    return [by_index[key] for key in sorted(by_index)]


def _shot_text_for_audit(shot: dict[str, Any]) -> str:
    parts = [
        shot.get("prompt"),
        shot.get("ref_prompt"),
        shot.get("description"),
        shot.get("voiceover"),
        shot.get("dialogue"),
        shot.get("subtitle"),
    ]
    return " ".join(str(part or "").strip() for part in parts if str(part or "").strip())


def _has_image_boundary_signal(shot: dict[str, Any]) -> bool:
    return bool(
        shot.get("selected_image")
        or shot.get("image_candidates")
        or shot.get("image_candidate")
        or shot.get("planned_reference")
        or shot.get("prompt")
    )


def _has_visual_marker_for_audit(shot: dict[str, Any]) -> bool:
    for key in (
        "visual_quality_rules",
        "quality_controls",
        "motion_controls",
        "negative_prompt",
        "lock_character",
        "lock_scene",
        "lock_costume",
        "lock_prop",
    ):
        if shot.get(key):
            return True
    return False


def _has_voice_text_for_audit(shot: dict[str, Any]) -> bool:
    text = _shot_text_for_audit(shot).lower()
    if any(shot.get(key) for key in ("voiceover", "dialogue", "subtitle", "tts_text")):
        return True
    return any(token in text for token in ("voiceover", "dialogue", "旁白", "对白", "台词", "tts"))


def _has_voice_payload_for_audit(shot: dict[str, Any]) -> bool:
    return any(
        bool(shot.get(key))
        for key in ("voice_delivery_rules", "tts_payload", "voice", "voiceover_audio", "tts_url", "audio_url", "voice_url")
    )


def _as_list_for_audit(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return []


def _examples_for_audit(shots: list[dict[str, Any]], key: str) -> list[str]:
    examples: list[str] = []
    for shot in shots:
        value = shot.get(key)
        if key == "prompt" and not value:
            value = _shot_text_for_audit(shot)
        if key == "voiceover" and not value:
            value = shot.get("dialogue") or shot.get("subtitle") or ""
        if isinstance(value, list):
            text = ", ".join(str(item) for item in value[:3])
        elif isinstance(value, dict):
            text = ", ".join(str(item) for item in list(value.keys())[:3])
        else:
            text = str(value or "").strip()
        if not text:
            continue
        examples.append(f"shot {shot.get('shot_index') or shot.get('index') or '?'}: {_excerpt(text, 90)}")
        if len(examples) >= 3:
            break
    return examples


def _audit_evidence(label: str, applied_count: int, candidate_count: int, examples: list[str]) -> str:
    suffix = f"; examples={' | '.join(examples)}" if examples else ""
    return f"{label}: applied={applied_count}; candidate={candidate_count}{suffix}"


def _build_continuity_handoff_audit(
    *,
    continuity_ledger: dict[str, Any],
    production_ledger: dict[str, Any],
    signals: dict[str, Any],
    phase: str,
    next_action: str,
) -> list[dict[str, Any]]:
    continuity_ledger = continuity_ledger if isinstance(continuity_ledger, dict) else {}
    production_ledger = production_ledger if isinstance(production_ledger, dict) else {}
    scenes = continuity_ledger.get("scenes") if isinstance(continuity_ledger.get("scenes"), list) else []
    current = continuity_ledger.get("current_segment") or continuity_ledger.get("current_scene")
    current = current if isinstance(current, dict) else {}
    previous_scene = continuity_ledger.get("previous_segment") or continuity_ledger.get("previous_scene")
    previous_scene = previous_scene if isinstance(previous_scene, dict) else {}
    next_scene = continuity_ledger.get("next_segment") or continuity_ledger.get("next_scene")
    next_scene = next_scene if isinstance(next_scene, dict) else {}
    gaps = continuity_ledger.get("continuity_gaps") if isinstance(continuity_ledger.get("continuity_gaps"), list) else []
    questions = continuity_ledger.get("handoff_questions") if isinstance(continuity_ledger.get("handoff_questions"), list) else []
    production_current = production_ledger.get("current_scene") if isinstance(production_ledger.get("current_scene"), dict) else {}

    def row(
        component: str,
        label: str,
        present: bool,
        consumed_by: list[str],
        evidence: str,
        decision_effect: str,
        gap: str,
        *,
        expected: bool = True,
    ) -> dict[str, Any]:
        if not expected:
            coverage = "covered"
        elif present and consumed_by:
            coverage = "covered"
        elif present:
            coverage = "partial"
        else:
            coverage = "missing"
        return {
            "component": component,
            "label": label,
            "present": bool(present),
            "consumed_by": consumed_by,
            "evidence": evidence,
            "decision_effect": decision_effect,
            "coverage": coverage,
            "gap": "" if coverage == "covered" else gap,
        }

    current_key = str(current.get("scene_key") or production_current.get("scene_key") or "")
    has_previous_expected = _scene_position_index(scenes, current_key) > 0
    has_next_expected = 0 <= _scene_position_index(scenes, current_key) < len(scenes) - 1
    handoff_codes = [str(item.get("code") or "") for item in gaps if isinstance(item, dict)]
    handoff_gap_count = sum(1 for code in handoff_codes if code in {"scene_handoff_check", "scene_count_mismatch"})
    decision_consumed = ["story_continuity_ledger", "debug_flow"]
    if handoff_gap_count:
        decision_consumed.append("risks")
    return [
        row(
            "scene_position",
            "第几集第几场",
            bool(current_key and current.get("episode") and current.get("scene")),
            ["story_continuity_ledger", "production_ledger", "debug_flow"],
            f"current={current_key or '-'}; episode={current.get('episode') or '-'}; scene={current.get('scene') or '-'}; scene_count={len(scenes)}",
            "用于页面和大脑摘要定位当前场，不再只看当前 20 个镜头。",
            "没有解析到 episode/scene/scene_key，说明分镜或场次文档缺少结构化场号。",
        ),
        row(
            "minute_position",
            "属于第几分钟",
            bool(current.get("minute_range") or production_ledger.get("current_minute_range")),
            ["story_continuity_ledger", "production_ledger", "progress_summary"],
            (
                f"minute_range={current.get('minute_range') or '-'}; "
                f"generated={signals.get('ledger_generated_video_seconds')}s; "
                f"remaining={signals.get('ledger_remaining_seconds')}s; "
                f"target={signals.get('ledger_target_total_seconds')}s"
            ),
            "用于判断 40 分钟长片已经推进到哪一段，以及还差多少秒。",
            "没有分钟区间时，只能看到分镜列表，无法知道它处在长片的哪一分钟。",
        ),
        row(
            "previous_scene",
            "前一场承接",
            bool(previous_scene),
            ["story_continuity_ledger", "handoff_questions"] if previous_scene else [],
            f"previous={previous_scene.get('scene_key') or '-'}; goal={_excerpt(str(previous_scene.get('goal') or previous_scene.get('summary') or ''), 120)}",
            "用于判断上一场讲到哪里，当前场开头是否接得住。",
            "当前不是第一场但没有 previous_scene，会丢失上一场情绪/剧情状态。",
            expected=has_previous_expected,
        ),
        row(
            "next_scene",
            "下一场承接",
            bool(next_scene),
            ["story_continuity_ledger", "handoff_questions"] if next_scene else [],
            f"next={next_scene.get('scene_key') or '-'}; goal={_excerpt(str(next_scene.get('goal') or next_scene.get('summary') or ''), 120)}",
            "用于判断当前场结尾要给下一场留下什么钩子或视觉锚点。",
            "当前不是最后一场但没有 next_scene，会导致后续生成只看眼前镜头。",
            expected=has_next_expected,
        ),
        row(
            "handoff_gaps",
            "承接缺口",
            bool(gaps or questions),
            decision_consumed,
            f"gap_count={len(gaps)}; handoff_gap_count={handoff_gap_count}; questions={len(questions)}; codes={', '.join(handoff_codes[:6]) or '-'}",
            "承接缺口会进入审计和风险提示；调试期先提示，不直接阻断所有生成。",
            "没有 continuity_gaps/handoff_questions 时，无法证明大脑检查过前后场关系。",
        ),
        row(
            "decision_influence",
            "是否影响下一步",
            bool(phase and next_action),
            ["phase", "next_action", "risks"] if handoff_gap_count else ["phase", "next_action"],
            f"phase={phase}; next_action={next_action}; continuity_score={continuity_ledger.get('continuity_score')}; bridge={continuity_ledger.get('scene_bridge_label') or '-'}",
            "当前会影响可视化判断和风险提示；强阻断策略需要在第 5 步成本风控中继续收紧。",
            "如果 future phase/next_action 完全不引用承接账本，这里会显示为 partial。",
        ),
    ]


def _scene_position_index(scenes: list[Any], current_key: str) -> int:
    if not current_key:
        return -1
    for idx, scene in enumerate(scenes):
        if isinstance(scene, dict) and scene.get("scene_key") == current_key:
            return idx
    return -1


def _build_cost_control_audit(
    *,
    cost_ledger: dict[str, Any],
    visual_budget: dict[str, Any],
    signals: dict[str, Any],
    risks: list[dict[str, Any]],
    phase: str,
    next_action: str,
) -> list[dict[str, Any]]:
    cost_ledger = cost_ledger if isinstance(cost_ledger, dict) else {}
    limits = cost_ledger.get("limits") if isinstance(cost_ledger.get("limits"), dict) else {}
    estimated = cost_ledger.get("estimated_operations") if isinstance(cost_ledger.get("estimated_operations"), dict) else {}
    risk_codes = {str(item.get("code") or "") for item in risks if isinstance(item, dict)}
    pending_image = int(signals.get("operational_pending_keyframe_count") or estimated.get("image") or 0)
    pending_video = int(signals.get("operational_pending_video_count") or estimated.get("video") or 0)
    image_batch_max = int(limits.get("image_batch_max") or 0)
    video_batch_max = int(limits.get("video_batch_max") or 0)
    visual_plan_actions = int(signals.get("visual_plan_action_count") or 0)
    bind_existing = int(signals.get("visual_bind_existing_count") or 0)
    avoided = int(signals.get("seedream_avoided_image_count") or 0)
    budget_level = str(signals.get("seedream_budget_level") or visual_budget.get("budget_level") or "ok")

    def row(
        component: str,
        label: str,
        present: bool,
        enforced_by: list[str],
        evidence: str,
        decision_effect: str,
        gap: str,
    ) -> dict[str, Any]:
        if present and enforced_by:
            coverage = "covered"
        elif present:
            coverage = "partial"
        else:
            coverage = "missing"
        return {
            "component": component,
            "label": label,
            "present": bool(present),
            "enforced_by": enforced_by,
            "evidence": evidence,
            "decision_effect": decision_effect,
            "coverage": coverage,
            "gap": "" if coverage == "covered" else gap,
        }

    return [
        row(
            "small_step_keyframes",
            "关键帧小步推进",
            image_batch_max > 0,
            ["workbench._continue_generate_keyframes", "BRAIN_KEYFRAME_BATCH_MAX"] if image_batch_max > 0 else [],
            f"pending_keyframes={pending_image}; batch_max={image_batch_max}; next_action={next_action}",
            f"大脑继续推进一次最多派发 {image_batch_max or 0} 个 Seedream 关键帧任务。",
            "没有关键帧批量上限时，继续推进可能一次性烧完整批 Seedream。",
        ),
        row(
            "small_step_videos",
            "视频小步推进",
            video_batch_max > 0,
            ["workbench._continue_generate_videos", "BRAIN_VIDEO_BATCH_MAX"] if video_batch_max > 0 else [],
            f"pending_videos={pending_video}; batch_max={video_batch_max}; next_action={next_action}",
            f"大脑继续推进一次最多派发 {video_batch_max or 0} 个 Seedance 视频任务，避免视频额度突发消耗。",
            "没有视频批量上限时，Seedance 风险不可控。",
        ),
        row(
            "asset_reuse_first",
            "资产复用优先",
            bool(cost_ledger.get("reuse_first")) or bind_existing > 0 or avoided > 0,
            ["visual_planner", "cost_risk_ledger", "plan_visual_assets"] if cost_ledger.get("reuse_first") or visual_plan_actions else [],
            f"reuse_first={cost_ledger.get('reuse_first')}; visual_actions={visual_plan_actions}; bind_existing={bind_existing}; avoided_seedream={avoided}",
            "预算高或有视觉资产规划时，先走 plan_visual_assets，把可复用角色/场景/服装/道具绑定出来。",
            "没有复用优先信号时，系统可能把每个镜头都当成新资产生成。",
        ),
        row(
            "budget_gate",
            "Seedream 预算闸门",
            budget_level in {"ok", "watch", "over_budget"},
            ["_decide_phase", "visual_budget_review", "seedream_budget_overrun"] if budget_level == "over_budget" else ["cost_risk_ledger"],
            f"budget_level={budget_level}; estimated_seedream={signals.get('seedream_estimated_image_count')}; without_reuse={signals.get('seedream_estimated_without_reuse')}",
            "Seedream 预算 over_budget 时，大脑会转入 plan_visual_assets，而不是直接 generate_keyframes。",
            "没有预算等级时，无法判断是否应该先复用资产再生成。",
        ),
        row(
            "credit_guard",
            "积分余额闸门",
            True,
            ["assert_cost_guard", "reserve_credits", "refund_on_failure"],
            "continue keyframes/videos reserve credits after batch cap; failure path refunds reserved transactions.",
            "实际派发前先按小批量预扣，余额不足会阻断；异常时退回已预扣。",
            "如果缺少预扣/退款链路，失败或超额时会产生财务风险。",
        ),
        row(
            "rate_concurrency_guard",
            "限流与并发闸门",
            True,
            ["check_concurrent_limit", "check_rate_limit"],
            "continue keyframes uses image_gen rate limit; continue videos uses video_gen rate limit.",
            "每次派发前检查用户并发和速率，防止同一用户短时间堆积任务。",
            "如果缺少限流并发检查，自动大脑可能和手动操作叠加冲垮队列。",
        ),
        row(
            "handoff_cost_guard",
            "承接风险进入风控",
            True,
            ["director_ledger_risks", "cost_control_audit", "debug_flow"] if "story_handoff_gap" in risk_codes else ["story_continuity_ledger"],
            f"story_handoff_gap={'story_handoff_gap' in risk_codes}; phase={phase}; next_action={next_action}",
            "多场承接缺口会进入风险提示；第 5 步后续可按该风险禁止大批量生成。",
            "承接风险还未作为强制停止条件，只能提示，不能完全防止错误方向消耗。",
        ),
    ]


def _build_final_delivery_audit(
    *,
    operational_shots: list[dict[str, Any]],
    workspace_shots: list[Any],
    final_edit_plan: dict[str, Any] | None,
    final_quality_ledger: dict[str, Any],
    signals: dict[str, Any],
    phase: str,
    next_action: str,
) -> list[dict[str, Any]]:
    shots = _merge_shot_rows_for_audit(workspace_shots, operational_shots)
    final_edit_plan = final_edit_plan if isinstance(final_edit_plan, dict) else {}
    quality = final_quality_ledger if isinstance(final_quality_ledger, dict) else {}
    settings = final_edit_plan.get("settings") if isinstance(final_edit_plan.get("settings"), dict) else {}
    preview_export = settings.get("preview_export") if isinstance(settings.get("preview_export"), dict) else {}
    final_export = settings.get("final_export") if isinstance(settings.get("final_export"), dict) else {}
    final_delivery_report = settings.get("final_delivery_report") if isinstance(settings.get("final_delivery_report"), dict) else {}
    clips = [clip for clip in (final_edit_plan.get("clips") if isinstance(final_edit_plan.get("clips"), list) else []) if isinstance(clip, dict)]
    enabled_clips = [clip for clip in clips if clip.get("enabled", True)]
    blocking_codes = {
        str(item.get("code") or "")
        for item in quality.get("blocking_items", [])
        if isinstance(item, dict)
    }
    shot_count = len(shots)
    video_done = sum(1 for shot in shots if shot.get("selected_video") or _status(shot) in {"video_done", "done", "final_done", "exported"})
    missing_video = quality.get("missing_video_shots") if isinstance(quality.get("missing_video_shots"), list) else []
    voice_required = any(_has_voice_text_for_audit(shot) for shot in shots)
    voice_ready = any(_has_voice_payload_for_audit(shot) for shot in shots) or any(
        bool(clip.get("audio_url") or clip.get("voice_url") or clip.get("tts_url"))
        for clip in clips
    )
    bgm_path = str(settings.get("bgm_path") or final_edit_plan.get("bgm_path") or "").strip()
    subtitles_enabled = bool(settings.get("burn_subtitles", True))
    missing_subtitles = [
        int(clip.get("shot_index") or 0)
        for clip in enabled_clips
        if subtitles_enabled and not str(clip.get("subtitle") or "").strip()
    ]
    enabled_video_clips = [clip for clip in enabled_clips if str(clip.get("video_url") or clip.get("src") or "").strip()]
    review_blockers = quality.get("review_blockers") if isinstance(quality.get("review_blockers"), list) else []
    delivery_ready = not blocking_codes and bool(enabled_video_clips)

    def row(
        component: str,
        label: str,
        present: bool,
        required: bool,
        checked_by: list[str],
        evidence: str,
        decision_effect: str,
        gap: str,
    ) -> dict[str, Any]:
        if not required:
            coverage = "covered"
        elif present and checked_by:
            coverage = "covered"
        elif present:
            coverage = "partial"
        else:
            coverage = "missing"
        return {
            "component": component,
            "label": label,
            "required": bool(required),
            "present": bool(present),
            "checked_by": checked_by,
            "evidence": evidence,
            "decision_effect": decision_effect,
            "coverage": coverage,
            "gap": "" if coverage == "covered" else gap,
        }

    return [
        row(
            "video_complete",
            "视频素材齐全",
            shot_count > 0 and video_done >= shot_count and not missing_video,
            shot_count > 0,
            ["final_quality_ledger", "missing_video_shots", "plan_final_edit/open_final_cut"],
            f"video_done={video_done}; shot_count={shot_count}; missing_video={', '.join(str(x) for x in missing_video[:12]) or '-'}",
            "视频未齐时 blocking_items 会出现 missing_video，不能进入可靠成片。",
            "还有镜头没有 selected_video，剪辑台只能剪已生成片段，不能代表完整成片。",
        ),
        row(
            "voiceover_tts_ready",
            "配音/TTS齐全",
            (not voice_required) or voice_ready,
            voice_required,
            ["final_quality_ledger", "audio_or_voice_ready", "voice_delivery_rules"],
            f"voice_required={voice_required}; voice_ready={voice_ready}; missing_audio={'missing_audio' in blocking_codes}",
            "有台词/旁白但没有音频时会阻塞最终交付；无台词项目可视为可选。",
            "检测到台词/旁白，但没有 tts_url/audio_url/voiceover_audio/TTS payload。",
        ),
        row(
            "bgm_ready",
            "BGM齐全",
            bool(bgm_path),
            bool(clips or video_done),
            ["final_quality_ledger", "final_edit_plan.settings.bgm_path", "final-cut UI"],
            f"bgm_path={bgm_path or '-'}; missing_bgm={'missing_bgm' in blocking_codes}; clips={len(clips)}",
            "有成片素材后缺 BGM 会进入 missing_bgm，提示先选音乐再交付。",
            "有视频/剪辑片段但没有 bgm_path，商业成片听感不完整。",
        ),
        row(
            "edit_plan_complete",
            "剪辑方案齐全",
            bool(enabled_video_clips) and "edit_plan_incomplete" not in blocking_codes,
            video_done > 0 or bool(clips),
            ["final_quality_ledger", "final_edit_plan.clips", "merge_plan_with_shots"],
            f"clips={len(clips)}; enabled_video_clips={len(enabled_video_clips)}; produced_video_count={quality.get('produced_video_count')}; incomplete={'edit_plan_incomplete' in blocking_codes}",
            "剪辑方案缺失或未覆盖已生成视频时会阻塞预览/导出判断。",
            "没有可用 enabled clips 或 clip 没有 video_url，FFmpeg 无法生成有效成片。",
        ),
        row(
            "subtitles_ready",
            "字幕齐全",
            not missing_subtitles,
            subtitles_enabled and bool(enabled_clips),
            ["final_quality_ledger", "final_edit.export_payload_from_plan", "video_edit subtitles"],
            f"burn_subtitles={subtitles_enabled}; missing_subtitle_clips={', '.join(str(x) for x in missing_subtitles[:12]) or '-'}",
            "开启字幕烧录时，缺字幕会降低交付完整度并进入验收扣分。",
            "已开启 burn_subtitles，但部分 clip 没有 subtitle。",
        ),
        row(
            "reviews_passed",
            "素材审查通过",
            not review_blockers and "review_not_passed" not in blocking_codes,
            bool(shots),
            ["final_quality_ledger", "image/video review statuses"],
            f"review_blockers={len(review_blockers)}; blocking_review={'review_not_passed' in blocking_codes}",
            "图片/视频 review 失败或 regenerate 状态会阻塞成片交付。",
            "存在 failed/rejected/regenerate 素材，不应直接导出商业成片。",
        ),
        row(
            "preview_export_ready",
            "预览/导出就绪",
            delivery_ready,
            bool(clips or video_done),
            ["director.export-preview", "director.export-final", "final_quality_ledger"] if delivery_ready else ["final_quality_ledger"],
            f"delivery_ready={delivery_ready}; acceptance={quality.get('acceptance_status')}; phase={phase}; next_action={next_action}",
            "所有阻塞项清空且有可用 clips 后，可以进入预览小样或最终导出。",
            "仍有 blocking_items 或没有可用剪辑片段，预览/导出只会得到不完整结果。",
        ),
        row(
            "preview_export_done",
            "预览小样已导出",
            bool(preview_export.get("url")),
            delivery_ready,
            ["director.export-preview", "final_edit_plan.settings.preview_export"],
            f"task_id={preview_export.get('task_id') or '-'}; url={preview_export.get('url') or '-'}",
            "预览导出完成后，用户可以检查节奏、字幕和音频再进入最终导出。",
            "尚未生成预览小样，最终导出前缺少可复核样片。",
        ),
        row(
            "final_export_done",
            "最终成片已导出",
            bool(final_export.get("url")) and bool(final_delivery_report.get("passed")),
            delivery_ready,
            ["director.export-final", "final_delivery_report", "ffprobe"],
            f"task_id={final_export.get('task_id') or '-'}; passed={bool(final_delivery_report.get('passed'))}; url={final_export.get('url') or '-'}",
            "最终导出通过质检后，项目可进入交付/发布。",
            "最终成片还未导出或质检未通过。",
        ),
    ]


def _build_feedback_loop_audit(
    *,
    operational_shots: list[dict[str, Any]],
    workspace_shots: list[Any],
    final_edit_plan: dict[str, Any] | None,
    decisions_doc: str,
    failures_doc: str,
    signals: dict[str, Any],
    phase: str,
    next_action: str,
) -> list[dict[str, Any]]:
    shots = _merge_shot_rows_for_audit(workspace_shots, operational_shots)
    final_edit_plan = final_edit_plan if isinstance(final_edit_plan, dict) else {}
    clips = final_edit_plan.get("clips") if isinstance(final_edit_plan.get("clips"), list) else []
    queued_or_running = [
        shot for shot in shots
        if "generating" in _status(shot) or "running" in _status(shot) or "queued" in _status(shot)
    ]
    media_done = [
        shot for shot in shots
        if shot.get("selected_image") or shot.get("selected_video") or _status(shot) in {"image_done", "video_done", "done"}
    ]
    failed = [shot for shot in shots if shot.get("last_error") or _status(shot) == "error"]
    decisions_has_continue = "project_brain_continue" in decisions_doc
    failures_has_writeback = "media_task_writeback" in failures_doc or bool(failed)

    def row(
        component: str,
        label: str,
        present: bool,
        read_next_by: list[str],
        evidence: str,
        decision_effect: str,
        gap: str,
    ) -> dict[str, Any]:
        if present and read_next_by:
            coverage = "covered"
        elif present:
            coverage = "partial"
        else:
            coverage = "missing"
        return {
            "component": component,
            "label": label,
            "present": bool(present),
            "read_next_by": read_next_by,
            "evidence": evidence,
            "decision_effect": decision_effect,
            "coverage": coverage,
            "gap": "" if coverage == "covered" else gap,
        }

    return [
        row(
            "workspace_decision_memory",
            "执行决策写回记忆",
            bool(decisions_doc.strip()),
            ["read_project_workspace", "context_coverage", "ledger_merge_audit"],
            f"decision_count={signals.get('decision_count')}; has_project_brain_continue={decisions_has_continue}",
            "下一轮大脑会重新读取 memory/decisions.md，用于审计做过什么和为什么做。",
            "没有决策记忆时，下一轮只能看当前状态，无法追溯上次为何派发任务。",
        ),
        row(
            "shot_row_status_writeback",
            "镜头状态写回",
            bool(shots),
            ["workbench.get_project_brain", "build_project_brain.operational_shots", "production_ledger"],
            (
                f"shots={len(shots)}; queued_or_running={len(queued_or_running)}; "
                f"image_done={signals.get('operational_image_done_count')}; "
                f"video_done={signals.get('operational_video_done_count')}; failed={len(failed)}"
            ),
            "下一轮大脑从 shot_rows 重建图片/视频进度、剩余秒数、下一步动作。",
            "没有 shot_rows 回写时，大脑会退化为只看 workspace 分镜，无法接着生成。",
        ),
        row(
            "media_success_writeback",
            "媒体成功结果写回",
            bool(media_done),
            ["image_tasks.update_shot_media", "video_tasks.update_shot_media", "selected_image/selected_video"],
            f"media_done_rows={len(media_done)}; selected_images={signals.get('operational_image_done_count')}; selected_videos={signals.get('operational_video_done_count')}",
            "Seedream/Seedance 成功后写 selected_image/selected_video，下一轮据此进入视频生成或最终剪辑。",
            "没有 selected_image/selected_video 时，成功结果没有成为下一轮输入。",
        ),
        row(
            "failure_writeback",
            "失败结果写回",
            bool(failed) or bool(failures_doc.strip()),
            ["update_shot_error", "memory/failures.md", "risk_detection"],
            f"failed_rows={len(failed)}; failure_count={signals.get('failure_count')}; has_media_task_writeback={failures_has_writeback}",
            "失败会写 shot_rows.last_error；媒体任务失败还会追加 memory/failures.md，下一轮进入风险提示。",
            "失败如果只停留在任务日志，下一轮大脑就会重复踩同一个坑。",
        ),
        row(
            "final_edit_writeback",
            "剪辑方案写回",
            bool(clips),
            ["final_edit_plans", "get_project_brain.final_edit_plan", "final_delivery_audit"],
            f"final_edit_plan_ready={signals.get('final_edit_plan_ready')}; clip_count={len(clips)}",
            "保存的 final_edit_plan 会被下一轮大脑读取，用于 open_final_cut 和交付检查。",
            "没有 final_edit_plan 时，下一轮无法知道剪辑顺序、BGM、字幕和导出设置。",
        ),
        row(
            "after_brain_refresh",
            "执行后刷新大脑",
            bool(phase and next_action),
            ["continueProjectBrain.after", "refreshProjectState", "getProjectBrain"],
            f"phase={phase}; next_action={next_action}; generated_seconds={signals.get('ledger_generated_video_seconds')}; remaining_seconds={signals.get('ledger_remaining_seconds')}",
            "继续推进接口返回 after，前端随后刷新 workspace/brain/shots，下一轮从持久化状态继续。",
            "没有 after/refresh 时，页面可能显示旧状态，导致重复执行同一步。",
        ),
    ]


def _build_content_signals(*, episodes_doc: str, scene_doc: str, characters_doc: str) -> dict[str, bool]:
    sources = {
        "has_director_plan": f"{episodes_doc}\n{scene_doc}",
        "has_character_lock": characters_doc,
        "has_scene_plan": scene_doc,
    }
    return {key: _content_signal_passes(sources[key], *spec) for key, spec in CONTENT_SIGNAL_SPECS.items()}


def _content_signal_passes(text: str, markers: tuple[str, ...], min_chars: int, section_heading: str) -> bool:
    marker_present = any(marker in text for marker in markers)
    if not marker_present:
        return False
    scoped = (
        _markdown_section(text, section_heading)
        if section_heading
        else text
    )
    return _has_substantive_workspace_text(scoped or text, min_chars=min_chars)


def _markdown_section(text: str, heading: str, *, level: int = 3) -> str:
    prefix = "#" * max(1, level) + " "
    lines = str(text or "").splitlines()
    capture = False
    captured: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix) and heading in stripped:
            capture = True
            continue
        if capture and re.match(r"^#{1,6}\s+", stripped):
            break
        if capture:
            captured.append(line)
    return "\n".join(captured).strip()


def _has_substantive_workspace_text(text: str, *, min_chars: int) -> bool:
    cleaned_lines = []
    for line in str(text or "").splitlines():
        clean = _substantive_line(line)
        if not clean:
            continue
        cleaned_lines.append(clean)
    clean_text = "\n".join(cleaned_lines)
    if len(clean_text) < min_chars:
        return False
    if re.fullmatch(r"[\W_?，,。.\s]+", clean_text):
        return False
    return True


def _substantive_line(line: str) -> str:
    clean = str(line or "").strip(" \t-#：:")
    if not clean:
        return ""
    if any(fragment.lower() in clean.lower() for fragment in PLACEHOLDER_FRAGMENTS):
        return ""
    if any(fragment in clean for fragment in DOC_MARKER_FRAGMENTS):
        return ""
    field_match = re.fullmatch(r"([^:：]+)[:：]?", clean)
    if field_match and field_match.group(1).strip() in EMPTY_FIELD_LABELS:
        return ""
    return clean


def _collect_risks(workspace_shots: list[Any], operational_shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for item in workspace_shots:
        if not isinstance(item, dict):
            continue
        preflight = item.get("director_preflight") if isinstance(item.get("director_preflight"), dict) else {}
        level = str(preflight.get("risk_level") or "").strip()
        if level == "blocked":
            risks.append({
                "code": "workspace_preflight_blocked",
                "severity": "blocked",
                "title": f"Shot {item.get('shot_index') or '?'} preflight blocked",
                "reason": _first_risk_reason(preflight),
            })
    for item in operational_shots:
        preflight = item.get("director_preflight") if isinstance(item.get("director_preflight"), dict) else {}
        if item.get("last_error"):
            severity = "blocked" if _is_blocking_error(item) else "warning"
            risks.append({
                "code": "shot_last_error",
                "severity": severity,
                "title": f"Shot {item.get('shot_index') or item.get('index') or '?'} has error",
                "reason": str(item.get("last_error")),
            })
        if str(preflight.get("risk_level") or "") == "blocked":
            risks.append({
                "code": "operational_preflight_blocked",
                "severity": "blocked",
                "title": f"Shot {item.get('shot_index') or item.get('index') or '?'} preflight blocked",
                "reason": _first_risk_reason(preflight),
            })
    return risks


def _is_blocking_error(item: dict[str, Any]) -> bool:
    if item.get("selected_image") and not item.get("selected_video"):
        return False
    status = _status(item)
    if status in {"image_done", "video_retryable", "video_failed"}:
        return False
    return True


def _status(item: dict[str, Any]) -> str:
    return str(item.get("status") or "").strip().lower()


def _count_generating(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if "generating" in _status(item) or "running" in _status(item))


def _count_generating_keyframes(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if _status(item) in {"generating_image", "running_image"})


def _count_generating_videos(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if _status(item) in {"generating_video", "running_video"})


def _count_pending_keyframes(items: list[dict[str, Any]]) -> int:
    return sum(
        1
        for item in items
        if item.get("prompt")
        and not item.get("selected_image")
        and "generating" not in _status(item)
        and "running" not in _status(item)
    )


def _count_image_done(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if bool(item.get("selected_image")) or _status(item) == "image_done")


def _count_pending_videos(items: list[dict[str, Any]]) -> int:
    return sum(
        1
        for item in items
        if (item.get("selected_image") or _status(item) == "image_done")
        and not item.get("selected_video")
        and "generating" not in _status(item)
        and "running" not in _status(item)
    )


def _count_video_done(items: list[dict[str, Any]]) -> int:
    return sum(
        1
        for item in items
        if bool(item.get("selected_video")) or _status(item) in {"video_done", "done", "final_done", "exported"}
    )


def _build_production_ledger(
    *,
    project_doc: str,
    episodes_doc: str,
    scene_doc: str,
    workspace_shots: list[Any],
    operational_shots: list[dict[str, Any]],
) -> dict[str, Any]:
    shots = _merge_ledger_shots(workspace_shots, operational_shots)
    planned_duration = round(sum(_shot_duration(item) for item in shots), 3)
    generated_duration = round(
        sum(_shot_duration(item) for item in shots if item.get("selected_video") or _status(item) in {"video_done", "done", "final_done", "exported"}),
        3,
    )
    target_total = _infer_target_total_seconds(project_doc, episodes_doc, scene_doc, shots)
    remaining = max(0.0, round(target_total - generated_duration, 3))
    scenes = _ledger_scenes(shots)
    current_scene = _current_scene(scenes)
    current_start = max(0.0, generated_duration)
    current_end = min(float(target_total), current_start + max(0.0, float(current_scene.get("planned_duration_seconds") or 0)))
    asset_locks = _ledger_asset_locks(shots)
    return {
        "target_total_seconds": int(round(target_total)),
        "target_total_label": _duration_label(target_total),
        "planned_shot_count": len(shots),
        "planned_duration_seconds": int(round(planned_duration)),
        "planned_duration_label": _duration_label(planned_duration),
        "generated_video_count": sum(1 for item in shots if item.get("selected_video") or _status(item) in {"video_done", "done", "final_done", "exported"}),
        "generated_video_seconds": int(round(generated_duration)),
        "generated_video_label": _duration_label(generated_duration),
        "remaining_seconds": int(round(remaining)),
        "remaining_label": _duration_label(remaining),
        "completion_percent": int(round(100 * generated_duration / max(target_total, 1))),
        "current_minute_start": int(current_start // 60) + 1 if target_total else 0,
        "current_minute_end": int(max(current_start, current_end) // 60) + 1 if target_total else 0,
        "current_scene": current_scene,
        "previous_scene": _previous_scene(scenes, current_scene),
        "next_scene": _next_scene(scenes, current_scene),
        "scenes": scenes,
        "asset_locks": asset_locks,
        "continuity_questions": _ledger_questions(current_scene, scenes, asset_locks, target_total, generated_duration),
    }


def _merge_ledger_shots(workspace_shots: list[Any], operational_shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_index: dict[int, dict[str, Any]] = {}
    for raw in workspace_shots:
        if not isinstance(raw, dict):
            continue
        idx = _shot_index(raw)
        if idx is not None:
            by_index[idx] = dict(raw)
    for raw in operational_shots:
        if not isinstance(raw, dict):
            continue
        idx = _shot_index(raw)
        if idx is None:
            continue
        base = by_index.get(idx, {})
        by_index[idx] = {**base, **raw}
    return [by_index[key] for key in sorted(by_index)]


def _shot_index(item: dict[str, Any]) -> int | None:
    for key in ("shot_index", "index", "shot_number"):
        value = item.get(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _shot_duration(item: dict[str, Any]) -> float:
    try:
        duration = float(item.get("duration") or item.get("duration_seconds") or 5.0)
    except (TypeError, ValueError):
        duration = 5.0
    return max(0.1, duration)


def _infer_target_total_seconds(project_doc: str, episodes_doc: str, scene_doc: str, shots: list[dict[str, Any]]) -> float:
    haystack = "\n".join(
        [
            project_doc,
            episodes_doc,
            scene_doc,
            "\n".join(str(item.get("prompt") or item.get("raw_text") or "") for item in shots[:80]),
        ]
    )
    minute_values = []
    for match in re.finditer(r"(\d{1,3})\s*(?:分钟|min|minutes?)", haystack, flags=re.IGNORECASE):
        value = int(match.group(1))
        if 10 <= value <= 240:
            minute_values.append(value)
    if minute_values:
        return float(max(minute_values) * 60)
    planned = sum(_shot_duration(item) for item in shots)
    return float(max(planned, 60.0 if shots else 0.0))


def _ledger_scenes(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for shot in shots:
        episode, scene = _episode_scene(shot)
        key = f"E{episode:02d}S{scene:02d}"
        if key not in groups:
            groups[key] = {
                "scene_key": key,
                "episode": episode,
                "scene": scene,
                "title": f"第{episode}集第{scene}场",
                "shot_count": 0,
                "image_done_count": 0,
                "video_done_count": 0,
                "planned_duration_seconds": 0,
                "generated_video_seconds": 0,
                "first_shot_index": _shot_index(shot) or 0,
                "last_shot_index": _shot_index(shot) or 0,
                "summary": "",
            }
            order.append(key)
        group = groups[key]
        duration = _shot_duration(shot)
        group["shot_count"] += 1
        group["planned_duration_seconds"] += duration
        group["last_shot_index"] = _shot_index(shot) or group["last_shot_index"]
        if shot.get("selected_image") or _status(shot) == "image_done":
            group["image_done_count"] += 1
        if shot.get("selected_video") or _status(shot) in {"video_done", "done", "final_done", "exported"}:
            group["video_done_count"] += 1
            group["generated_video_seconds"] += duration
        if not group["summary"]:
            group["summary"] = _scene_summary_from_prompt(str(shot.get("prompt") or shot.get("raw_text") or ""))
    result = []
    for key in order:
        group = groups[key]
        group["planned_duration_seconds"] = int(round(group["planned_duration_seconds"]))
        group["generated_video_seconds"] = int(round(group["generated_video_seconds"]))
        group["completion_percent"] = int(round(100 * group["video_done_count"] / max(group["shot_count"], 1)))
        result.append(group)
    return result


def _episode_scene(shot: dict[str, Any]) -> tuple[int, int]:
    prompt = str(shot.get("prompt") or shot.get("raw_text") or "")
    for episode_key, scene_key in (("episode", "scene"), ("episode_index", "scene_index")):
        try:
            episode = int(shot.get(episode_key))
            scene = int(shot.get(scene_key))
        except (TypeError, ValueError):
            continue
        if episode > 0 and scene > 0:
            return episode, scene
    match = re.search(r"第\s*(\d+)\s*集\s*第\s*(\d+)\s*场", prompt)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"\bE(?:P)?\s*(\d{1,2})\s*S(?:C)?\s*(\d{1,2})\b", prompt, flags=re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"\bEpisode\s*(\d{1,2})\s*Scene\s*(\d{1,2})\b", prompt, flags=re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 1, 1


def _scene_summary_from_prompt(prompt: str) -> str:
    text = re.sub(r"^第\s*\d+\s*集\s*第\s*\d+\s*场[，,：:\s]*", "", prompt).strip()
    return _excerpt(text, 120)


def _current_scene(scenes: list[dict[str, Any]]) -> dict[str, Any]:
    for scene in scenes:
        if scene.get("video_done_count", 0) < scene.get("shot_count", 0):
            return dict(scene)
    return dict(scenes[-1]) if scenes else {}


def _previous_scene(scenes: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
    key = current.get("scene_key")
    for idx, scene in enumerate(scenes):
        if scene.get("scene_key") == key and idx > 0:
            return dict(scenes[idx - 1])
    return {}


def _next_scene(scenes: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
    key = current.get("scene_key")
    for idx, scene in enumerate(scenes):
        if scene.get("scene_key") == key and idx + 1 < len(scenes):
            return dict(scenes[idx + 1])
    return {}


def _ledger_asset_locks(shots: list[dict[str, Any]]) -> dict[str, Any]:
    fields = {
        "character": ("character_refs", "character_refs_json"),
        "scene": ("scene_refs", "scene_refs_json"),
        "costume": ("costume_refs", "costume_refs_json"),
        "prop": ("prop_refs", "prop_refs_json"),
        "style": ("style_refs", "style_refs_json"),
    }
    locked: dict[str, list[str]] = {}
    for label, keys in fields.items():
        values: list[str] = []
        for shot in shots:
            for key in keys:
                for item in _as_strings(shot.get(key)):
                    if item not in values:
                        values.append(item)
        locked[label] = values
    reusable = {key: value for key, value in locked.items() if value}
    return {
        "locked": locked,
        "locked_total": sum(len(value) for value in locked.values()),
        "reusable": reusable,
        "reusable_total": sum(len(value) for value in reusable.values()),
    }


def _as_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item.get("asset_id") if isinstance(item, dict) else item).strip() for item in value if str(item.get("asset_id") if isinstance(item, dict) else item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _ledger_questions(
    current_scene: dict[str, Any],
    scenes: list[dict[str, Any]],
    asset_locks: dict[str, Any],
    target_total: float,
    generated_duration: float,
) -> list[str]:
    questions = []
    if current_scene:
        questions.append(f"当前推进到 {current_scene.get('title')}，视频完成 {current_scene.get('video_done_count')}/{current_scene.get('shot_count')}。")
    if target_total and generated_duration < target_total:
        questions.append(f"已生成 {_duration_label(generated_duration)}，距离目标 {_duration_label(target_total)} 还差 {_duration_label(target_total - generated_duration)}。")
    if scenes:
        questions.append("下一批必须承接上一场落点，不能只生成孤立镜头。")
    if asset_locks.get("reusable_total"):
        questions.append(f"已有 {asset_locks.get('reusable_total')} 个可复用资产锚点，后续优先复用再生成。")
    else:
        questions.append("角色、服装、场景锚点不足，继续生成前应先锁定可复用资产。")
    return questions


def _duration_label(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes = total // 60
    remain = total % 60
    if minutes <= 0:
        return f"{remain}秒"
    if remain == 0:
        return f"{minutes}分钟"
    return f"{minutes}分{remain}秒"


def _visual_budget(visual_plan: dict[str, Any] | None, operational_shots: list[dict[str, Any]]) -> dict[str, Any]:
    budget = visual_plan.get("seedream_budget") if isinstance(visual_plan, dict) and isinstance(visual_plan.get("seedream_budget"), dict) else None
    if budget:
        return {
            "action_count": _int(budget.get("action_count")),
            "bind_existing_count": _int(budget.get("bind_existing_count")),
            "generate_reference_count": _int(budget.get("unique_reference_generation_count"), _int(budget.get("generate_reference_action_count"))),
            "pending_keyframes": _int(budget.get("pending_keyframe_count"), _count_pending_keyframes(operational_shots)),
            "estimated_seedream_images": _int(budget.get("estimated_seedream_images")),
            "estimated_without_reuse": _int(budget.get("estimated_without_reuse")),
            "avoided_seedream_images": _int(budget.get("avoided_seedream_images")),
            "reuse_ratio_percent": _int(budget.get("reuse_ratio_percent"), 100),
            "budget_level": str(budget.get("budget_level") or "ok"),
            "recommendations": budget.get("recommendations") if isinstance(budget.get("recommendations"), list) else [],
        }
    actions = visual_plan.get("asset_actions") if isinstance(visual_plan, dict) and isinstance(visual_plan.get("asset_actions"), list) else []
    bind_existing_count = sum(1 for item in actions if isinstance(item, dict) and item.get("action_type") == "bind_existing")
    generate_reference_actions = [
        item
        for item in actions
        if isinstance(item, dict) and item.get("action_type") == "generate_reference"
    ]
    generate_reference_count = len({_reference_group_key(item) for item in generate_reference_actions})
    pending_keyframes = _count_pending_keyframes(operational_shots)
    estimated_without_reuse = len(generate_reference_actions) + pending_keyframes
    estimated_seedream_images = generate_reference_count + pending_keyframes
    avoided = max(0, estimated_without_reuse - estimated_seedream_images + bind_existing_count)
    return {
        "action_count": len(actions),
        "bind_existing_count": bind_existing_count,
        "generate_reference_count": generate_reference_count,
        "pending_keyframes": pending_keyframes,
        "estimated_seedream_images": estimated_seedream_images,
        "estimated_without_reuse": estimated_without_reuse,
        "avoided_seedream_images": avoided,
        "reuse_ratio_percent": int(round(100 * (bind_existing_count + generate_reference_count) / max(bind_existing_count + len(generate_reference_actions), 1))) if actions else 100,
        "budget_level": _seedream_budget_level(estimated_seedream_images),
        "recommendations": [],
    }


def _reference_group_key(action: dict[str, Any]) -> str:
    kind = str(action.get("kind") or "").strip().lower()
    title = str(action.get("title") or "").strip().lower()
    prompt_seed = str(action.get("prompt_seed") or "").strip().lower()
    # Prompt seed includes shot-level details; title usually captures the reusable subject
    # such as main character, store scene, prop, costume, or overall style.
    return f"{kind}:{title or prompt_seed[:80]}"


def _first_risk_reason(preflight: dict[str, Any]) -> str:
    risks = preflight.get("risks") if isinstance(preflight.get("risks"), list) else []
    for item in risks:
        if isinstance(item, dict) and item.get("reason"):
            return str(item.get("reason"))
    return "Preflight requires correction before production."


def _collect_missing(signals: dict[str, Any], risks: list[dict[str, Any]]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    if not signals["workspace_ready"]:
        missing.append({"code": "workspace_files", "label": "Project workspace files are incomplete."})
    if not signals["has_director_plan"]:
        missing.append({"code": "story_plan", "label": "Story understanding and episode/scene plan are not persisted yet."})
    if not signals["has_character_lock"]:
        missing.append({"code": "asset_locks", "label": "Character, scene, prop, or style locks are not persisted yet."})
    if not signals["has_scene_plan"]:
        missing.append({"code": "scene_plan", "label": "Current scene plan is not persisted yet."})
    if signals["workspace_shot_count"] <= 0 and signals["operational_shot_count"] <= 0:
        missing.append({"code": "shot_plan", "label": "Structured shot plan is empty."})
    if any(item.get("severity") == "blocked" for item in risks):
        missing.append({"code": "risk_resolution", "label": "Blocked production risks need correction."})
    if signals.get("seedream_budget_level") == "over_budget":
        missing.append({"code": "visual_budget_review", "label": "Seedream image budget is high; reuse and prioritization are required before batch keyframes."})
    return missing


def _build_safety_gates(*, signals: dict[str, Any], risks: list[dict[str, Any]], next_action: str) -> list[dict[str, Any]]:
    blocked_risks = [item for item in risks if item.get("severity") == "blocked"]
    gates = []
    for spec in SAFETY_GATE_SPECS:
        passed = _safety_condition_passes(str(spec["ok"]), signals, blocked_risks)
        severity = str(spec.get("severity") or "blocked")
        required_for = tuple(spec["for"])
        reason = _first_blocked_risk_reason(blocked_risks) if spec["id"] == "preflight_clear" and not passed else str(spec["reason"])
        evidence_keys = tuple(spec["evidence"])
        evidence = {key: signals.get(key) for key in evidence_keys if key != "blocked_risk_count"}
        if "blocked_risk_count" in evidence_keys:
            evidence["blocked_risk_count"] = len(blocked_risks)
        gates.append({
            "id": spec["id"],
            "code": spec.get("code") or spec["id"],
            "label": spec["label"],
            "status": "pass" if passed else severity,
            "severity": "ok" if passed else severity,
            "passed": passed,
            "blocks_current_action": (not passed) and next_action in required_for,
            "required_for": list(required_for),
            "reason": "" if passed else reason,
            "evidence": evidence,
        })
    return gates


def _safety_condition_passes(condition: str, signals: dict[str, Any], blocked_risks: list[dict[str, Any]]) -> bool:
    match condition:
        case "workspace_ready" | "has_director_plan" | "has_scene_plan" | "has_character_lock":
            return bool(signals.get(condition))
        case "has_shots":
            return int(signals.get("workspace_shot_count") or 0) > 0 or int(signals.get("operational_shot_count") or 0) > 0
        case "no_blocked_risks":
            return not blocked_risks
        case "visual_budget_ok":
            return signals.get("seedream_budget_level") != "over_budget"
        case "no_active_generation":
            return int(signals.get("operational_generating_count") or 0) <= 0
    raise ValueError(f"unsupported safety gate condition: {condition}")


def _first_blocked_risk_reason(blocked_risks: list[dict[str, Any]]) -> str:
    if not blocked_risks:
        return ""
    first = blocked_risks[0]
    return str(first.get("reason") or first.get("title") or "Blocked preflight risks must be resolved before generation.")




def _decide_phase(signals: dict[str, Any], risks: list[dict[str, Any]]) -> tuple[str, str]:
    if not signals["workspace_ready"]:
        return "script_understanding", "repair_workspace"
    if not signals["has_director_plan"]:
        return "script_understanding", "generate_story_plan"
    if not signals["has_scene_plan"]:
        return "episode_scene_planning", "plan_scene"
    if not signals["has_character_lock"]:
        return "asset_locking", "lock_assets"
    if signals["workspace_shot_count"] <= 0 and signals["operational_shot_count"] <= 0:
        return "storyboard_directing", "generate_storyboard"
    if any(item.get("severity") == "blocked" for item in risks):
        return "preflight_review", "fix_preflight_risks"
    if signals["operational_generating_video_count"] > 0:
        return "video_generation", "wait_for_videos"
    if signals["operational_generating_keyframe_count"] > 0 or signals["operational_generating_count"] > 0:
        return "keyframe_generation", "wait_for_keyframes"
    if signals.get("seedream_budget_level") == "over_budget" and signals["operational_pending_keyframe_count"] > 0:
        return "asset_locking", "plan_visual_assets"
    if signals["operational_pending_keyframe_count"] > 0 and signals["visual_plan_action_count"] > 0:
        return "asset_locking", "plan_visual_assets"
    if signals["operational_pending_keyframe_count"] > 0:
        return "keyframe_generation", "generate_keyframes"
    if signals["operational_pending_video_count"] > 0:
        return "video_generation", "generate_videos"
    if signals["final_edit_plan_ready"]:
        return "final_edit", "open_final_cut"
    if signals["operational_video_done_count"] > 0:
        return "final_edit", "plan_final_edit"
    if signals["workspace_shot_count"] > 0:
        return "keyframe_generation", "generate_keyframes"
    return "preflight_review", "run_preflight"


def _build_summary(phase: str, signals: dict[str, Any], risks: list[dict[str, Any]], missing: list[dict[str, str]]) -> str:
    if signals.get("seedream_budget_level") == "over_budget":
        return (
            f"图片预算偏高：预计 Seedream {signals.get('seedream_estimated_image_count')} 张，"
            f"复用后已少生成 {signals.get('seedream_avoided_image_count')} 张；先规划可复用资产再批量关键帧。"
        )
    if signals.get("operational_pending_video_count", 0) > 0:
        return (
            f"进度账本：已生成视频 {signals.get('operational_video_done_count')}/"
            f"{signals.get('operational_shot_count')} 镜，约 {signals.get('ledger_generated_video_seconds')} 秒；"
            f"目标约 {signals.get('ledger_target_total_seconds')} 秒，还差 {signals.get('ledger_remaining_seconds')} 秒。"
        )
    blocked_risks = [item for item in risks if item.get("severity") == "blocked"]
    if blocked_risks:
        return f"项目已读取，但有 {len(blocked_risks)} 个阻塞风险，需要先修复再继续生成。"
    if missing:
        return f"项目已读取，当前处于 {phase}，还缺 {len(missing)} 类关键信息。"
    if phase == "keyframe_generation":
        return "项目规划和分镜已落盘，下一步可以进入关键帧生成。"
    return f"项目已读取，当前阶段为 {phase}。"


def _next_action_label(next_action: str) -> str:
    if next_action == "open_final_cut":
        return "打开剪辑台"
    labels = {
        "choose_project": "选择项目",
        "repair_workspace": "修复项目工作区",
        "generate_story_plan": "生成剧本理解与场次规划",
        "plan_scene": "完善当前场次",
        "lock_assets": "锁定角色/场景/道具",
        "plan_visual_assets": "规划视觉资产",
        "generate_storyboard": "生成结构化分镜",
        "run_preflight": "执行生成前审查",
        "fix_preflight_risks": "修复高风险分镜",
        "generate_keyframes": "生成关键帧",
    }
    labels.update({
        "wait_for_keyframes": "等待关键帧回写",
        "wait_for_videos": "等待视频回写",
        "generate_videos": "生成视频",
        "plan_final_edit": "规划成片剪辑",
    })
    return labels.get(next_action, next_action)


def _excerpt(text: str, limit: int) -> str:
    clean = str(text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit] + "\n..."


def _collect_visual_budget_risks(visual_budget: dict[str, Any]) -> list[dict[str, Any]]:
    level = str(visual_budget.get("budget_level") or "")
    estimated = int(visual_budget.get("estimated_seedream_images") or 0)
    if level == "over_budget":
        return [{
            "code": "seedream_budget_overrun",
            "severity": "warning",
            "title": "Seedream image budget is high",
            "reason": f"Estimated {estimated} Seedream images before video generation. Plan reusable references before batch keyframes.",
        }]
    if level == "watch":
        return [{
            "code": "seedream_budget_watch",
            "severity": "info",
            "title": "Seedream image budget needs monitoring",
            "reason": f"Estimated {estimated} Seedream images. Generate critical references first and batch keyframes gradually.",
        }]
    return []


def _seedream_budget_level(estimated_images: int) -> str:
    if estimated_images >= 13:
        return "over_budget"
    if estimated_images >= 8:
        return "watch"
    return "ok"


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
