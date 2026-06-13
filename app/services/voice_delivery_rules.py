from __future__ import annotations

import re
from typing import Any


_TENSE_HINTS = ("紧张", "害怕", "不安", "犹豫", "隐忍", "委屈", "哽咽", "微颤", "低语", "断续")
_WARM_HINTS = ("温柔", "撒娇", "治愈", "轻声", "柔和", "想我", "终于来了")
_WARNING_HINTS = ("警告", "严肃", "生气", "愤怒", "压迫", "反派", "冷笑", "听懂了吗")
_PAUSE_PUNCTUATION = ("，", "。", "？", "！", "；", "、", "…", "~")


def prepare_tts_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Compile creator voice-delivery rules into executable TTS parameters.

    The function deliberately avoids injecting bracketed acting directions into
    the spoken text, because many TTS providers will read them aloud. We only
    adjust punctuation rhythm and numeric controls that the existing TTS API can
    execute today.
    """
    prepared = dict(payload or {})
    text = str(prepared.get("text") or "")
    inferred = infer_voice_controls(
        " ".join(
            str(prepared.get(key) or "")
            for key in ("text", "scene", "character_state", "emotion", "style")
        )
    )
    prepared["text"] = shape_tts_text(text, force_pause=inferred["delivery_profile"] == "tense_breathing_pauses")
    prepared.setdefault("speed", inferred["speed"])
    if prepared.get("volume") is None:
        prepared["volume"] = inferred["volume"]
    prepared["delivery_profile"] = inferred["delivery_profile"]
    return prepared


def shape_tts_text(text: str, *, force_pause: bool = False) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return text
    if any(mark in text for mark in _PAUSE_PUNCTUATION):
        return text
    if force_pause and len(text) >= 8:
        midpoint = _choose_short_pause_index(text)
        return f"{text[:midpoint]}，{text[midpoint:]}"
    if len(text) <= 18:
        return text

    return _insert_soft_pauses(text)


def infer_voice_controls(context: str) -> dict[str, Any]:
    text = re.sub(r"\s+", "", str(context or ""))
    if _contains_any(text, _WARNING_HINTS):
        return {
            "speed": 0.92,
            "volume": 1.05,
            "delivery_profile": "warning_slow_pressure",
        }
    if _contains_any(text, _TENSE_HINTS):
        return {
            "speed": 0.86,
            "volume": 0.95,
            "delivery_profile": "tense_breathing_pauses",
        }
    if _contains_any(text, _WARM_HINTS):
        return {
            "speed": 0.9,
            "volume": 0.98,
            "delivery_profile": "warm_soft_tail",
        }
    return {
        "speed": 1.0,
        "volume": 1.0,
        "delivery_profile": "neutral_clear",
    }


def _insert_soft_pauses(text: str) -> str:
    chunks: list[str] = []
    start = 0
    for index in range(12, len(text), 12):
        if index - start < 8:
            continue
        chunks.append(text[start:index])
        start = index
    chunks.append(text[start:])
    return "，".join(chunk for chunk in chunks if chunk)


def _choose_short_pause_index(text: str) -> int:
    for marker in ("不是", "就", "才", "还", "我", "你", "他", "她"):
        index = text.find(marker)
        if 3 <= index <= len(text) - 3:
            return index
    return max(4, len(text) // 2)


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)
