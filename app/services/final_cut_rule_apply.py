from __future__ import annotations

from typing import Any

from app.services.final_edit import normalize_edit_plan


def apply_final_cut_rule(plan: dict[str, Any], recipe_id: str) -> dict[str, Any]:
    normalized = normalize_edit_plan(plan)
    recipe_id = str(recipe_id or "").strip()
    if recipe_id == "cinematic_pacing_slow_fast_slow":
        return _apply_slow_fast_slow(normalized)
    if recipe_id == "closeup_group_to_wide_tension":
        return _apply_closeup_to_wide(normalized)
    if recipe_id == "travel_vlog_segmented_story":
        return _apply_travel_vlog_segments(normalized)
    return {
        "plan": normalized,
        "explanation": ["该规则暂时只作为剪辑思维参考，尚未提供本地自动应用。"],
        "warnings": [],
        "applied": False,
    }


def _apply_slow_fast_slow(plan: dict[str, Any]) -> dict[str, Any]:
    clips = [dict(clip) for clip in plan.get("clips", [])]
    if len(clips) < 3:
        return {
            "plan": plan,
            "explanation": ["慢-快-慢至少需要3个可用镜头。"],
            "warnings": ["当前镜头数量不足，未自动调整。"],
            "applied": False,
        }

    scored = [_with_role_scores(clip) for clip in clips]
    opening = _pick_best(scored, "slow_opening")
    ending = _pick_best([item for item in scored if item["clip"]["shot_index"] != opening["clip"]["shot_index"]], "slow_ending")
    middle = [
        item for item in scored
        if item["clip"]["shot_index"] not in {opening["clip"]["shot_index"], ending["clip"]["shot_index"]}
    ]
    middle.sort(key=lambda item: item["fast_middle"], reverse=True)
    arranged = [opening["clip"], *[item["clip"] for item in middle], ending["clip"]]

    total = len(arranged)
    for idx, clip in enumerate(arranged, 1):
        clip["order"] = idx
        clip["enabled"] = True
        duration = float(clip.get("duration") or 5)
        if idx == 1:
            _target_effective_duration(clip, min(duration, max(6.0, min(8.0, duration))))
            clip["transition"] = "fade"
        elif idx == total:
            _target_effective_duration(clip, min(duration, max(7.0, min(9.0, duration))))
            clip["transition"] = "fade"
        else:
            _target_effective_duration(clip, min(duration, 3.0))
            clip["transition"] = "cut"

    output = normalize_edit_plan({"version": 1, "settings": {**plan.get("settings", {}), "transition": "fade"}, "clips": arranged})
    return {
        "plan": output,
        "explanation": [
            "已按慢-快-慢重排镜头。",
            "中段镜头压缩到约3秒快切。",
            "开场和结尾保留慢节奏留白。",
        ],
        "warnings": [],
        "applied": True,
    }


def _apply_closeup_to_wide(plan: dict[str, Any]) -> dict[str, Any]:
    clips = [dict(clip) for clip in plan.get("clips", [])]
    if len(clips) < 2:
        return {
            "plan": plan,
            "explanation": ["特写组接大全景至少需要2个镜头。"],
            "warnings": ["当前镜头数量不足，未自动调整。"],
            "applied": False,
        }
    scored = [_with_role_scores(clip) for clip in clips]
    closeups = sorted(scored, key=lambda item: item["closeup"], reverse=True)
    wide = _pick_best(scored, "wide")
    wide_idx = wide["clip"]["shot_index"]
    arranged = [item["clip"] for item in closeups if item["clip"]["shot_index"] != wide_idx]
    arranged = arranged[:4] + [wide["clip"]]
    used = {clip["shot_index"] for clip in arranged}
    arranged.extend([clip for clip in clips if clip["shot_index"] not in used])
    for idx, clip in enumerate(arranged, 1):
        clip["order"] = idx
        if idx < len(arranged) and idx <= 4:
            _target_effective_duration(clip, min(float(clip.get("duration") or 5), 2.0))
            clip["transition"] = "cut"
        elif clip["shot_index"] == wide_idx:
            _target_effective_duration(clip, min(float(clip.get("duration") or 5), 6.0))
            clip["transition"] = "fade"
    return {
        "plan": normalize_edit_plan({"version": 1, "settings": plan.get("settings", {}), "clips": arranged}),
        "explanation": ["已将特写镜头前置快切，并把大全景放在后段释放空间感。"],
        "warnings": [],
        "applied": True,
    }


def _apply_travel_vlog_segments(plan: dict[str, Any]) -> dict[str, Any]:
    result = _apply_slow_fast_slow(plan)
    if result["applied"]:
        settings = dict(result["plan"].get("settings") or {})
        settings["transition"] = "fade"
        result["plan"]["settings"] = settings
        result["explanation"] = [
            "已按旅拍分段思路处理为平静-热闹-治愈。",
            "中段使用快切，结尾保留长镜头。",
        ]
    return result


def _with_role_scores(clip: dict[str, Any]) -> dict[str, Any]:
    text = f"{clip.get('prompt', '')} {clip.get('subtitle', '')}".lower()
    duration = float(clip.get("duration") or 5)
    closeup_words = ("特写", "手部", "细节", "美食", "纹理", "close", "detail")
    wide_words = ("全景", "大全景", "远山", "航拍", "空镜", "风景", "wide", "landscape")
    ending_words = ("结尾", "背影", "晚霞", "日落", "治愈", "留白", "ending", "sunset")
    hot_words = ("热闹", "市集", "动作", "互动", "快切", "高能", "人群", "action")
    closeup = _count_matches(text, closeup_words)
    wide = _count_matches(text, wide_words)
    ending = _count_matches(text, ending_words)
    hot = _count_matches(text, hot_words)
    return {
        "clip": clip,
        "slow_opening": wide * 3 + (1 if duration >= 6 else 0),
        "fast_middle": closeup * 2 + hot * 3 + (1 if duration <= 6 else 0),
        "slow_ending": ending * 4 + wide + (1 if duration >= 7 else 0),
        "closeup": closeup * 3 + hot,
        "wide": wide * 3 + ending,
    }


def _pick_best(items: list[dict[str, Any]], key: str) -> dict[str, Any]:
    if not items:
        raise ValueError("No clips available")
    return sorted(items, key=lambda item: (item.get(key, 0), -int(item["clip"].get("order") or 0)), reverse=True)[0]


def _count_matches(text: str, words: tuple[str, ...]) -> int:
    return sum(1 for word in words if word in text)


def _target_effective_duration(clip: dict[str, Any], target: float) -> None:
    duration = max(0.1, float(clip.get("duration") or 0.1))
    target = max(0.1, min(float(target), duration))
    clip["trim_start"] = 0.0
    clip["trim_end"] = round(max(0.0, duration - target), 3)
