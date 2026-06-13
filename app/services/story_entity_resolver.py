"""Resolve named cultural/story entities before storyboard generation.

The production chain must not treat a specific work title as a generic noun.
This module keeps deterministic project-level facts that are safe to use as
anchors when the user references a known drama, actor, role, or source work.
"""

from __future__ import annotations

from typing import Any


def resolve_story_entity(instruction: str) -> dict[str, Any] | None:
    text = str(instruction or "")
    compact = "".join(text.split())
    if _looks_like_zhang_jiayi_drama_protagonist(compact):
        return {
            "resolver_version": "story_entity_resolver_v1",
            "match": "zhang_jiayi_tv_drama_zhuju",
            "work_title": "主角",
            "work_type": "电视剧",
            "source_note": "改编自陈彦同名小说，秦腔/县剧团题材。",
            "actor": "张嘉益",
            "role_name": "胡三元",
            "role_identity": "县剧团司鼓、秦腔人",
            "story_world": "西北县剧团、秦腔班社、舞台后台与排练场",
            "scene_anchors": ["县剧团后台", "排练场", "戏台边", "锣鼓点旁"],
            "prop_anchors": ["鼓槌", "锣鼓家伙", "戏服", "旧谱本", "搪瓷缸"],
            "action_anchors": ["敲鼓点", "看排练", "训戏", "带外甥女入戏门", "整理戏服"],
            "tone_anchors": ["西北年代烟火气", "秦腔舞台气息", "剧团人情"],
            "must_not": ["泛化成无身份电视剧男主", "写成现代办公室/派出所模板", "空镜替代胡三元"],
        }
    return None


def _looks_like_zhang_jiayi_drama_protagonist(text: str) -> bool:
    has_actor = "张嘉益" in text
    has_drama = "电视剧" in text or "剧" in text or "最近很火" in text
    has_title_or_generic = "主角" in text
    return has_actor and has_drama and has_title_or_generic
