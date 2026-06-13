from __future__ import annotations

from typing import Any


def build_edit_strategy(
    *,
    goal: str,
    shot_rows: list[dict[str, Any]],
    target_duration_sec: int,
) -> dict[str, Any]:
    """Build a small, executable editing strategy from known editing rules."""
    shot_count = len(shot_rows)
    rhythm = "slow-fast-slow" if shot_count >= 3 else "steady"
    techniques = [
        {
            "id": "slow_fast_slow",
            "label": "慢-快-慢节奏",
            "reason": "短剧预览需要先建立情境，中段推进冲突，结尾留情绪落点。",
        },
        {
            "id": "closeups_plus_wide",
            "label": "特写组 + 全景",
            "reason": "用特写承接情绪，用全景交代空间，避免流水账。",
        },
        {
            "id": "detail_transition",
            "label": "空镜/特写转场",
            "reason": "场次或情绪切换时插入细节镜头，减少跳切感。",
        },
        {
            "id": "music_fade_bridge",
            "label": "音乐淡入淡出",
            "reason": "没有精确卡点音频时，先用柔和淡入淡出保证衔接自然。",
        },
        {
            "id": "subtitle_emotion_cues",
            "label": "字幕承接情绪",
            "reason": "短视频预览必须让观众快速读懂冲突和情绪。",
        },
    ]
    transitions = []
    for index in range(max(0, shot_count - 1)):
        transitions.append({
            "from": int(shot_rows[index].get("shot_index") or index + 1),
            "to": int(shot_rows[index + 1].get("shot_index") or index + 2),
            "type": "fade" if index in {0, shot_count - 2} else "cut",
            "reason": "首尾柔和过渡，中段保持推进节奏。",
        })
    cursor = 0.0
    subtitles = []
    for row in shot_rows:
        duration = float(row.get("duration") or 5.0)
        subtitles.append({
            "shot_index": int(row.get("shot_index") or len(subtitles) + 1),
            "start": round(cursor, 3),
            "end": round(cursor + duration, 3),
            "text": _subtitle_text(row, goal),
        })
        cursor += duration
    return {
        "version": 1,
        "goal": goal,
        "target_duration_sec": int(target_duration_sec or 15),
        "rhythm": rhythm,
        "techniques": techniques,
        "shot_grouping": [
            {
                "group": "opening",
                "shots": [int(shot_rows[0].get("shot_index") or 1)] if shot_rows else [],
                "purpose": "建立人物与场景",
            },
            {
                "group": "conflict",
                "shots": [int(row.get("shot_index") or idx + 1) for idx, row in enumerate(shot_rows[1:-1], 2)],
                "purpose": "推进动作和情绪",
            },
            {
                "group": "landing",
                "shots": [int(shot_rows[-1].get("shot_index") or shot_count)] if shot_count > 1 else [],
                "purpose": "留出情绪落点",
            },
        ],
        "transitions": transitions,
        "freeze_frames": [],
        "pip_layers": [],
        "text_overlays": [],
        "sound_effects": [],
        "bgm_plan": {
            "source": "none",
            "mood": "cinematic",
            "volume": 0.15,
            "reason": "当前最小闭环先保留原视频音轨；没有 BGM 时明确 none。",
        },
        "subtitles": subtitles,
    }


def _subtitle_text(row: dict[str, Any], goal: str) -> str:
    prompt = str(row.get("prompt") or "").strip()
    if prompt:
        return prompt[:42]
    goal = str(goal or "短剧预览").strip()
    return goal[:42] or "短剧预览"
