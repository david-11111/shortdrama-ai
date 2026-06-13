"""Build a story-understanding card before production planning."""

from __future__ import annotations

import re
from typing import Any

from app.services.story_entity_resolver import resolve_story_entity


def build_story_understanding(instruction: str) -> dict[str, Any]:
    text = str(instruction or "").strip()
    entity = resolve_story_entity(text)
    mentions_real_work = _mentions_real_work(text)
    ambiguity = _ambiguity_flags(text, entity=entity)
    missing = _missing_understanding_fields(text, entity=entity, mentions_real_work=mentions_real_work)
    sufficient = not missing and not ambiguity
    if entity:
        sufficient = True
    return {
        "version": "story_understanding_v1",
        "raw_instruction": text,
        "mentions_real_work": mentions_real_work,
        "entity_resolution": entity or {},
        "ambiguity_flags": ambiguity,
        "missing_fields": missing,
        "sufficient_for_storyboard": sufficient,
        "required_steps": _required_steps(entity=entity, missing=missing, ambiguity=ambiguity),
        "understanding_card": _understanding_card(text, entity=entity),
    }


def _mentions_real_work(text: str) -> bool:
    return any(term in text for term in ("电视剧", "电影", "综艺", "小说", "最近很火", "主演", "饰演", "演的", "复拍"))


def _ambiguity_flags(text: str, *, entity: dict[str, Any] | None) -> list[str]:
    flags: list[str] = []
    if "主角" in text and not entity and _mentions_real_work(text):
        flags.append("title_or_generic_protagonist_ambiguous")
    if re.search(r"[\u4e00-\u9fff]{2,4}(?:演的|饰演|主演)", text) and not entity:
        flags.append("actor_role_needs_fact_check")
    return flags


def _missing_understanding_fields(
    text: str,
    *,
    entity: dict[str, Any] | None,
    mentions_real_work: bool,
) -> list[str]:
    if entity:
        return []
    missing: list[str] = []
    if mentions_real_work:
        missing.extend(["work_title", "role_name", "role_identity", "story_world"])
    if not any(term in text for term in ("场景", "后台", "排练", "办公室", "医院", "街道", "金店", "柜台", "家里", "学校")):
        missing.append("scene_world")
    if not any(term in text for term in ("动作", "推门", "坐下", "递交", "敲", "看", "训", "拿", "转身", "冲突")):
        missing.append("action_goal")
    return list(dict.fromkeys(missing))


def _required_steps(
    *,
    entity: dict[str, Any] | None,
    missing: list[str],
    ambiguity: list[str],
) -> list[dict[str, str]]:
    steps = [
        {"id": "extract_entities", "status": "done", "purpose": "识别作品名、演员、角色、时间和用户目标。"},
    ]
    if entity:
        steps.append({"id": "resolve_real_work", "status": "done", "purpose": "把真实作品/角色事实写入项目约束。"})
    elif missing or ambiguity:
        steps.append({"id": "resolve_real_work", "status": "blocked", "purpose": "真实作品或角色未确认前，不能泛化成普通短剧模板。"})
    steps.append({
        "id": "build_story_card",
        "status": "done" if entity or not missing else "blocked",
        "purpose": "形成角色、世界、场景、动作、道具、禁用项。",
    })
    steps.append({
        "id": "derive_storyboard",
        "status": "ready" if entity or not missing else "blocked",
        "purpose": "分镜必须从剧情理解卡派生。",
    })
    return steps


def _understanding_card(text: str, *, entity: dict[str, Any] | None) -> dict[str, Any]:
    if entity:
        return {
            "work": entity.get("work_title") or "",
            "actor": entity.get("actor") or "",
            "role": entity.get("role_name") or "",
            "role_identity": entity.get("role_identity") or "",
            "story_world": entity.get("story_world") or "",
            "scene_anchors": entity.get("scene_anchors") or [],
            "prop_anchors": entity.get("prop_anchors") or [],
            "action_anchors": entity.get("action_anchors") or [],
            "tone_anchors": entity.get("tone_anchors") or [],
            "must_not": entity.get("must_not") or [],
        }
    return {
        "work": "",
        "actor": _first_actor(text),
        "role": "",
        "role_identity": "",
        "story_world": "",
        "scene_anchors": [],
        "prop_anchors": [],
        "action_anchors": [],
        "tone_anchors": [],
        "must_not": ["不能在事实未确认时套用泛化短剧模板"],
    }


def _first_actor(text: str) -> str:
    match = re.search(r"([\u4e00-\u9fff]{2,4})(?:演的|饰演|主演)", text)
    return match.group(1) if match else ""
