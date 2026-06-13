from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services.story_understanding import build_story_understanding


logger = logging.getLogger(__name__)

REQUIRED_FACT_FIELDS = ("work", "role", "role_identity", "story_world")
PLACEHOLDER_VALUES = {
    "missing_fields",
    "missing_field",
    "unknown",
    "unk",
    "n/a",
    "na",
    "none",
    "null",
    "not sure",
    "not_found",
    "not found",
    "to_confirm",
    "tbd",
    "待确认",
    "待核实",
    "未知",
    "不明",
    "不确定",
    "无法确认",
    "未确认",
    "缺失",
    "空",
    "-",
}


async def build_story_understanding_with_llm(instruction: str, *, project_context: dict[str, Any] | None = None) -> dict[str, Any]:
    local = build_story_understanding(instruction)
    settings = get_settings()
    if not settings.deepseek_api_key:
        return {**local, "source": "local_fallback", "llm_error": "deepseek_api_key_not_configured"}
    try:
        llm_card = await _call_deepseek_story_understanding(instruction, project_context=project_context or {})
        merged = _merge_llm_card(local, llm_card)
        return {**merged, "source": "deepseek"}
    except Exception as exc:
        logger.warning("DeepSeek story understanding failed; using local fallback: %s", exc)
        return {**local, "source": "local_fallback", "llm_error": str(exc)}


async def _call_deepseek_story_understanding(instruction: str, *, project_context: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    system_prompt = (
        "你是短剧项目的剧情侦察员。你的任务不是写剧本，也不是写分镜。"
        "你只负责把用户需求里的真实作品、演员、角色、场景世界、动作目标、道具和禁用误解解析成 JSON。"
        "如果提到真实作品/演员/最近很火/复拍，你必须先识别作品事实；不知道就标记 missing_fields，不要编。"
        "返回 JSON，字段：work, actor, role, role_identity, story_world, scene_anchors, prop_anchors, action_anchors, tone_anchors, must_not, missing_fields, confidence, evidence_note。"
    )
    payload = {
        "instruction": instruction,
        "project_context": project_context,
        "output_contract": {
            "scene_anchors": "array of concrete locations",
            "prop_anchors": "array of visible props",
            "action_anchors": "array of playable actions",
            "must_not": "array of forbidden generic misunderstandings",
        },
    }
    request_body = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
        ],
        "temperature": 0.1,
        "max_tokens": 900,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    timeout = httpx.Timeout(connect=10.0, read=35.0, write=10.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        response.raise_for_status()
    data = response.json()
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    parsed = json.loads(content)
    return parsed if isinstance(parsed, dict) else {}


def _merge_llm_card(local: dict[str, Any], llm_card: dict[str, Any]) -> dict[str, Any]:
    card = _normalize_llm_card(llm_card)
    local_card = local.get("understanding_card") or {}
    merged_card: dict[str, Any] = dict(local_card)

    for key in ("work", "actor", "role", "role_identity", "story_world"):
        llm_value = card.get(key)
        local_value = local_card.get(key)
        if not _is_missing_value(llm_value):
            merged_card[key] = llm_value
        elif not _is_missing_value(local_value):
            merged_card[key] = local_value

    for key in ("scene_anchors", "prop_anchors", "action_anchors", "tone_anchors", "must_not"):
        llm_items = _clean_list(card.get(key) or [])
        local_items = _clean_list(local_card.get(key) or [])
        merged_card[key] = llm_items or local_items

    merged_card["evidence_note"] = "" if _is_missing_value(card.get("evidence_note")) else card.get("evidence_note", "")
    merged_card["confidence"] = card.get("confidence")

    missing = list(card.get("missing_fields") or [])
    for field in REQUIRED_FACT_FIELDS:
        if _is_missing_value(merged_card.get(field)):
            missing.append(field)
    missing = [
        str(item).strip()
        for item in missing
        if str(item).strip() in REQUIRED_FACT_FIELDS and _is_missing_value(merged_card.get(str(item).strip()))
    ]
    missing = list(dict.fromkeys(missing))
    sufficient = not missing
    return {
        **local,
        "mentions_real_work": bool(
            local.get("mentions_real_work")
            or not _is_missing_value(merged_card.get("work"))
            or not _is_missing_value(merged_card.get("actor"))
        ),
        "entity_resolution": local.get("entity_resolution") or {},
        "missing_fields": missing,
        "sufficient_for_storyboard": sufficient,
        "understanding_card": merged_card,
    }


def _normalize_llm_card(value: dict[str, Any]) -> dict[str, Any]:
    def _list(key: str) -> list[str]:
        raw = value.get(key)
        if isinstance(raw, list):
            return _clean_list(raw)
        if isinstance(raw, str) and not _is_missing_value(raw):
            return [raw.strip()]
        return []

    return {
        "work": _clean_scalar(value.get("work") or value.get("work_title")),
        "actor": _clean_scalar(value.get("actor")),
        "role": _clean_scalar(value.get("role") or value.get("role_name")),
        "role_identity": _clean_scalar(value.get("role_identity")),
        "story_world": _clean_scalar(value.get("story_world")),
        "scene_anchors": _list("scene_anchors"),
        "prop_anchors": _list("prop_anchors"),
        "action_anchors": _list("action_anchors"),
        "tone_anchors": _list("tone_anchors"),
        "must_not": _list("must_not"),
        "missing_fields": _list("missing_fields"),
        "evidence_note": _clean_scalar(value.get("evidence_note")),
        "confidence": value.get("confidence"),
    }


def _clean_scalar(value: Any) -> str:
    if _is_missing_value(value):
        return ""
    return str(value).strip()


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if not _is_missing_value(item)]


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, set)):
        return not any(not _is_missing_value(item) for item in value)
    text = str(value).strip()
    if not text:
        return True
    normalized = text.lower().strip(" \t\r\n:：,，.。[]()（）")
    return normalized in PLACEHOLDER_VALUES
