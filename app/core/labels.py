"""Centralized label mappings and constants.

All frontend-facing label dictionaries live here so they stay in sync
between Python and TypeScript.  The frontend can fetch labels via an API
endpoint generated from ``get_all_labels()``, eliminating hard-coded
duplication in Vue components.

Every service that needs a Chinese label imports from here instead of
defining its own ``{code: label}`` dict — this was the single most
duplicated pattern across the old codebase.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# ── Production-stage labels ─────────────────────────────────────────────────

STAGE_LABELS: dict[str, str] = {
    "Read project context": "读取项目上下文",
    "Generate script and storyboard plan": "生成剧本和分镜",
    "Plan visual assets": "规划视觉资产",
    "Lock reusable assets": "锁定可复用资产",
    "Generate keyframes": "生成关键帧",
    "generate_keyframes": "生成关键帧",
    "Review keyframes": "确认关键帧",
    "Generate videos": "生成视频",
    "generate_videos": "生成视频",
    "Review videos": "确认视频",
    "Produce audio, subtitles and BGM": "制作声音和字幕",
    "Build final cut": "合成成片",
    "Quality check": "质量检查",
    "Write back and review": "回写结果",
    "dispatching": "派发中",
    "running": "运行中",
    "completed": "已完成",
    "pending": "等待中",
    "blocked": "已阻断",
}

# ── Stage names (by pipeline id) ────────────────────────────────────────────

STAGE_NAMES: dict[str, str] = {
    "read_context": "读取项目上下文",
    "generate_story_plan": "生成剧本和分镜",
    "plan_visual_assets": "规划视觉资产",
    "lock_assets": "锁定可复用资产",
    "generate_keyframes": "生成关键帧",
    "review_keyframes": "确认关键帧",
    "generate_videos": "生成视频",
    "review_videos": "确认视频",
    "audio_subtitles": "制作声音和字幕",
    "final_cut": "合成成片",
    "quality_check": "质量检查",
    "writeback_review": "回写结果",
}

# ── Status labels ───────────────────────────────────────────────────────────

RUN_STATUS_LABELS: dict[str, str] = {
    "dispatching": "调度中",
    "running": "运行中",
    "provider_waiting": "等待 provider 恢复",
    "completed": "完成",
    "done": "完成",
    "failed": "失败",
    "blocked": "阻断",
    "cancelled": "已取消",
    "loading": "加载中",
    "created": "已创建",
    "queued": "排队中",
    "waiting_approval": "待确认",
}

COMPOSER_STATE_LABELS: dict[str, str] = {
    "idle": "待输入",
    "draft": "待发送",
    "running": "执行中",
    "failed": "失败",
    "saved": "已接收",
    "answered": "已答复",
    "dispatched": "已派发",
    "deferred": "已暂存",
    "rejected": "已拒绝",
}

# ── Action labels ───────────────────────────────────────────────────────────

ACTION_LABELS: dict[str, str] = {
    "status_query": "状态查询",
    "generate_story_plan": "剧本/分镜",
    "plan_visual_assets": "参考图/视觉资产",
    "generate_keyframes": "关键帧/出图",
    "generate_videos": "视频生成",
    "plan_final_edit": "剪辑/成片",
    "brain_next": "项目大脑下一步",
}

# ── Routing-source labels ───────────────────────────────────────────────────

ROUTING_SOURCE_LABELS: dict[str, str] = {
    "manual_selector": "手动指定",
    "status_query_rule": "状态规则命中",
    "natural_language_rule": "关键词规则命中",
    "brain_next_action": "交给项目大脑判断",
    "llm_planner": "DeepSeek 判断",
    "control_tool": "中控工具判断",
    "semantic_controller": "语义中控判断",
    "pending_action_confirm": "确认暂存动作",
}

# ── Executor labels ─────────────────────────────────────────────────────────

EXECUTOR_LABELS: dict[str, str] = {
    "DeepSeekConversation": "DeepSeek 对话",
    "RuntimeController": "运行时中控",
    "ProjectBrainExecutor": "项目大脑",
    "StatusQueryExecutor": "状态查询",
    "OutputDiagnosticExecutor": "成果诊断",
    "TaskDiagnosticExecutor": "任务诊断",
    "ProviderWritebackDiagnosticExecutor": "Provider 回写诊断",
    "ScriptDiagnosticExecutor": "剧本诊断",
    "KeyframePoolDiagnosticExecutor": "图片池诊断",
}

# ── Continuity-gap / missing-item labels ────────────────────────────────────

MISSING_ITEM_LABELS: dict[str, str] = {
    "shot_rows": "剧本/分镜",
    "selected_image": "关键帧",
    "image_task_failures": "失败的关键帧任务",
    "image_tasks_or_selected_images": "关键帧任务",
    "image_review_blockers": "未通过审查的关键帧",
    "selected_video": "视频片段",
    "video_task_failures": "失败的视频任务",
    "video_tasks_or_selected_videos": "视频任务",
    "video_review_blockers": "未通过审查的视频",
    "final_video_url": "成片文件",
    "generate_story_plan": "剧本/分镜阶段",
    "generate_keyframes": "关键帧阶段",
    "review_keyframes": "关键帧确认",
    "generate_videos": "视频生成阶段",
    "review_videos": "视频确认",
    "final_cut": "成片合成",
}

# ── Gate-reason labels ──────────────────────────────────────────────────────

GATE_REASON_LABELS: dict[str, str] = {
    "Script/storyboard rows must exist before visual assets or keyframes.": "需要先生成剧本和分镜，才能继续生成视觉资产。",
    "At least one selected keyframe is required before video generation.": "需要至少一张已确认关键帧，才能继续生成视频。",
    "Failed keyframe tasks must be resolved before keyframe review.": "有关键帧任务失败，需要先修复后再确认。",
    "Keyframe generation must run before keyframe review.": "需要先执行关键帧生成。",
    "Failed video tasks must be resolved before video review.": "有视频任务未完成，需要先恢复或重试后再确认。",
    "Video generation must run before video review.": "需要先执行视频生成。",
    "At least one selected video is required before audio/final cut.": "需要至少一个视频片段，才能继续合成成片。",
    "A final exported video is required before quality check.": "需要先导出成片，才能进行质量检查。",
    "Keyframe review found shots that must be regenerated before video generation.": "关键帧审查发现不合格镜头，需要先重做关键帧，再进入视频生成。",
    "Video review found clips that must be regenerated before final edit.": "视频审查发现不合格镜头，需要先重做视频片段，再进入剪辑成片。",
}

# ── Label accessor functions ────────────────────────────────────────────────


def stage_label(key: str, default: str = "等待中") -> str:
    return STAGE_LABELS.get(key, STAGE_NAMES.get(key, default))


def status_label(key: str, default: str = "") -> str:
    return RUN_STATUS_LABELS.get(key, default)


def action_label(key: str, default: str = "") -> str:
    return ACTION_LABELS.get(key, default)


def executor_label(key: str, default: str = "") -> str:
    return EXECUTOR_LABELS.get(key, default)


def routing_source_label(key: str, default: str = "") -> str:
    return ROUTING_SOURCE_LABELS.get(key, default)


def missing_item_label(key: str, default: str = "") -> str:
    return MISSING_ITEM_LABELS.get(key, default)


def gate_reason_label(key: str, default: str = "") -> str:
    return GATE_REASON_LABELS.get(key, default)


# ── Bulk export (for API endpoint) ──────────────────────────────────────────


def get_all_labels() -> dict[str, dict[str, str]]:
    """Return all label groups in a single dict.

    Can be served directly as ``/api/labels`` so the frontend never
    hard-codes a label string.
    """
    return {
        "stage": STAGE_LABELS,
        "stage_names": STAGE_NAMES,
        "run_status": RUN_STATUS_LABELS,
        "composer_state": COMPOSER_STATE_LABELS,
        "action": ACTION_LABELS,
        "routing_source": ROUTING_SOURCE_LABELS,
        "executor": EXECUTOR_LABELS,
        "missing_item": MISSING_ITEM_LABELS,
        "gate_reason": GATE_REASON_LABELS,
    }
