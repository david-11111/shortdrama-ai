"""User-intent classification — maps natural-language keywords to actions.

Deterministic, no LLM calls.  Uses Unicode-normalized matching against
a priority-ordered keyword table.
"""

from __future__ import annotations

import unicodedata

from app.core.types import ActionIntent

# Priority-ordered intent rules: (action, confidence, keywords)
_INTENT_RULES: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    ("generate_story_plan", 0.95, ("剧本", "劇本", "脚本", "腳本", "故事", "分镜", "分鏡", "台词", "臺詞", "对白", "對白", "修饰", "修飾", "润色", "潤色", "重写", "重寫", "从头", "從頭", "开始", "開始", "建立", "新建", "story", "script", "storyboard")),
    ("plan_visual_assets", 0.9, ("参考图", "參考圖", "参考图片", "參考圖片", "视觉", "視覺", "视觉资产", "視覺資產", "资产", "資產", "角色图", "角色圖", "场景图", "場景圖", "产品图", "產品圖", "seedream", "visual", "asset", "reference")),
    ("generate_keyframes", 0.85, ("关键帧", "關鍵幀", "图片", "圖片", "出图", "出圖", "首帧", "首幀", "尾帧", "尾幀", "画面不行", "畫面不行", "keyframe", "image")),
    ("plan_final_edit", 0.85, ("剪辑", "剪輯", "导出", "導出", "成片", "字幕", "配音", "音乐", "音樂", "final cut", "export", "bgm")),
    ("generate_videos", 0.85, ("视频", "視頻", "生成视频", "生成視頻", "运镜", "運鏡", "动作不行", "動作不行", "seedance", "kling", "video")),
)


def infer_continue_action(goal: str) -> str:
    """Return the action string with the best keyword match."""
    return infer_continue_action_decision(goal).action


def infer_continue_action_decision(goal: str) -> ActionIntent:
    """Classify user input into a structured action intent.

    Returns ``ActionIntent`` with ``action``, ``confidence``, and
    ``matched`` keywords.  Empty action means no rule matched.
    """
    text = unicodedata.normalize("NFKC", str(goal or "")).strip().lower()
    if not text:
        return ActionIntent(action="", confidence=0.0, matched=(), source="empty")

    for action, confidence, keywords in _INTENT_RULES:
        matched = tuple(k for k in keywords if k in text)
        if matched:
            return ActionIntent(action=action, confidence=confidence, matched=matched, source="natural_language_rule")

    return ActionIntent(action="", confidence=0.0, matched=(), source="no_match")
