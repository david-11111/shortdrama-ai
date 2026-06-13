from __future__ import annotations

import json
import re
from typing import Any

from app.services.doubao import generate_text
from app.services.final_edit import normalize_edit_plan


SYSTEM_PROMPT = """你是一个商业短视频剪辑策划师。你只能输出 JSON，不要输出 Markdown。

目标：根据剪辑规则、现有镜头和用户要求，生成可执行的 final edit plan。

必须遵守：
1. 只能使用输入中已有的 shot_index，不能新增镜头。
2. 不能编造 video_url、duration、prompt，这些字段由系统保留。
3. 只能调整 enabled、order、trim_start、trim_end、transition、subtitle、settings。
4. 输出必须是 JSON object，格式：
{
  "plan": {
    "version": 1,
    "settings": {
      "transition": "cut|fade|dissolve",
      "burn_subtitles": true,
      "subtitle_source": "prompt",
      "bgm_path": "",
      "bgm_volume": 0.15,
      "cover_title": "",
      "cover_frame_sec": null
    },
    "clips": [
      {
        "shot_index": 1,
        "order": 1,
        "enabled": true,
        "trim_start": 0,
        "trim_end": 0,
        "transition": "cut|fade|dissolve",
        "subtitle": "字幕"
      }
    ]
  },
  "explanation": ["为什么这样调整，最多3条，每条不超过30个中文字符"],
  "warnings": ["素材不足或规则无法完全执行的说明，最多2条"]
}
5. 不要使用“完美覆盖”“完全满足”等绝对化判断，只描述已依据哪些素材做了什么调整。
6. 输出要尽量短，禁止展开教程正文。
"""


def generate_final_cut_plan(
    api_key: str,
    *,
    recipe: dict[str, Any],
    current_plan: dict[str, Any],
    user_instruction: str = "",
) -> dict[str, Any]:
    normalized_current = normalize_edit_plan(current_plan)
    payload = {
        "recipe": _compact_recipe(recipe),
        "current_plan": _compact_plan(normalized_current),
        "user_instruction": str(user_instruction or "").strip(),
    }
    result = generate_text(
        api_key,
        {
            "system_prompt": SYSTEM_PROMPT,
            "prompt": json.dumps(payload, ensure_ascii=False),
            "temperature": 0.25,
            "max_tokens": 900,
        },
    )
    ai_object = _parse_json_object(result.get("text", ""))
    plan = _merge_ai_plan(normalized_current, ai_object.get("plan") or {})
    return {
        "plan": plan,
        "explanation": _string_list(ai_object.get("explanation")),
        "warnings": _string_list(ai_object.get("warnings")),
        "recipe_id": recipe.get("id"),
        "recipe_name": recipe.get("name"),
        "tokens_used": result.get("tokens_used", 0),
        "prompt_tokens": result.get("prompt_tokens", 0),
        "completion_tokens": result.get("completion_tokens", 0),
        "model": result.get("model"),
        "billing_usage": result.get("billing_usage"),
    }


def _compact_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id",
        "name",
        "category",
        "summary",
        "rules",
        "steps",
        "formula",
        "structure",
        "pacing_map",
        "planner_actions",
        "ffmpeg_feasibility",
        "needs_ai",
        "needs_assets",
    }
    return {key: recipe.get(key) for key in allowed if key in recipe}


def _compact_plan(plan: dict[str, Any]) -> dict[str, Any]:
    clips = []
    for clip in plan.get("clips", []):
        clips.append(
            {
                "shot_index": clip.get("shot_index"),
                "order": clip.get("order"),
                "enabled": clip.get("enabled"),
                "prompt": str(clip.get("prompt") or "")[:260],
                "duration": clip.get("duration"),
                "trim_start": clip.get("trim_start"),
                "trim_end": clip.get("trim_end"),
                "transition": clip.get("transition"),
                "subtitle": str(clip.get("subtitle") or "")[:180],
            }
        )
    return {
        "version": 1,
        "settings": plan.get("settings") or {},
        "clips": clips,
    }


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("AI returned empty final cut plan")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise ValueError("AI did not return a JSON object")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("AI final cut plan must be a JSON object")
    return parsed


def _merge_ai_plan(current_plan: dict[str, Any], ai_plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ai_plan, dict):
        raise ValueError("AI plan must be an object")
    base_by_shot = {
        int(clip["shot_index"]): dict(clip)
        for clip in current_plan.get("clips", [])
        if clip.get("shot_index") is not None
    }
    ai_clips = ai_plan.get("clips")
    if not isinstance(ai_clips, list):
        raise ValueError("AI plan clips must be a list")

    allowed_clip_fields = {"enabled", "order", "trim_start", "trim_end", "transition", "subtitle"}
    merged_clips = []
    seen: set[int] = set()
    for idx, ai_clip in enumerate(ai_clips, 1):
        if not isinstance(ai_clip, dict):
            continue
        try:
            shot_index = int(ai_clip.get("shot_index"))
        except (TypeError, ValueError):
            continue
        base = base_by_shot.get(shot_index)
        if not base or shot_index in seen:
            continue
        for key in allowed_clip_fields:
            if key in ai_clip:
                base[key] = ai_clip[key]
        base["order"] = int(base.get("order") or idx)
        merged_clips.append(base)
        seen.add(shot_index)

    for clip in current_plan.get("clips", []):
        shot_index = int(clip["shot_index"])
        if shot_index not in seen:
            merged_clips.append(dict(clip))

    settings = {
        **(current_plan.get("settings") or {}),
        **(ai_plan.get("settings") if isinstance(ai_plan.get("settings"), dict) else {}),
    }
    return normalize_edit_plan({"version": 1, "settings": settings, "clips": merged_clips})


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
