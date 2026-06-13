"""Prompt normalizer — slot extraction, deduplication, LLM polishing.

Pure standard-library implementation — no numpy, sklearn, sentence_transformers,
or rapidfuzz dependencies.  Deduplication uses difflib.SequenceMatcher.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

# ── Extended CJK range: covers Unified Ideographs Extensions A through G ────
#   Basic:         一-鿟  (U+4E00–U+9FFF)
#   Ext A:         㐀-䶿   (U+3400–U+4DBF)
#   Compat:        豈-﫿   (U+F900–U+FAFF)
#   Ext B:         \U00020000–\U0002A6DF
#   Ext C:         \U0002A700–\U0002B73F
#   Ext D:         \U0002B740–\U0002B81F
#   Ext E:         \U0002B820–\U0002CEAF
#   Ext F:         \U0002CEB0–\U0002EBE0
#   Ext G:         \U00030000–\U0003134F
""

# ── Constants ────────────────────────────────────────────────────────────────

SLOT_ORDER = ["scene", "style", "camera", "mood", "character", "lighting", "color", "constraint"]

VIDEO_WHITELIST: dict[str, list[str]] = {
    "style": ["古风", "仙侠", "电影感", "文艺", "留白", "低饱和", "山河", "史诗", "大片", "文旅"],
    "camera": ["镜头", "运镜", "推", "拉", "摇", "移", "转场", "过渡", "直切", "环绕", "升降", "航拍", "远景", "中景", "特写", "景别", "机位"],
    "mood": ["氛围", "意境", "情绪", "宿命", "清冷", "肃杀", "清宁", "压抑", "空灵", "朦胧"],
    "character": ["人物", "角色", "五官", "微表情", "表情", "仪态", "造型", "服化道", "站位", "气场", "人设"],
    "lighting": ["光线", "光影", "照明", "主光", "辅光", "逆光", "柔光", "漫射", "亮度", "层次"],
    "color": ["色调", "色彩", "影调", "冷暖", "色温", "青灰", "墨绿", "素白", "金辉"],
    "constraint": ["稳定", "统一", "连续", "不跳变", "不突兀", "不崩", "构图", "透视", "空间", "连贯", "禁止", "不跳轴", "不乱晃", "清晰"],
}

REF_WHITELIST: dict[str, list[str]] = {
    "style": VIDEO_WHITELIST["style"],
    "camera": ["构图", "远景", "中景", "特写", "景别", "站位", "俯拍", "平视"],
    "mood": VIDEO_WHITELIST["mood"],
    "character": ["人物", "五官", "造型", "服化道", "站位", "仪态", "角色稳定"],
    "lighting": VIDEO_WHITELIST["lighting"],
    "color": VIDEO_WHITELIST["color"],
    "constraint": ["统一", "稳定", "构图", "透视", "空间", "连续", "清晰"],
}

VIDEO_BLACKLIST = ["音效", "旁白", "台词", "口型", "配音", "解说", "心理", "内心", "文案", "字幕"]
REF_BLACKLIST = ["音效", "旁白", "台词", "口型", "配音", "解说", "字幕"]
META_BLACKLIST = ["适配", "工业标准", "完全隔离", "专用", "AI生成", "短视频", "现代剧", "TVC"]
AUDIO_BLACKLIST = ["底噪", "脚步", "开门", "点烟", "轻叹", "人声", "雨打", "车流", "环境音"]

STYLE_PRIORITY = {
    "古风仙侠": 100,
    "电影感": 88,
    "文旅大片": 80,
    "极简文艺": 74,
    "文艺": 70,
    "留白": 66,
}

_NO_MERGE_ANCHORS = [
    "光影", "色调", "构图", "透视", "空间",
    "稳定", "统一", "连续", "服化道", "五官",
    "运镜", "转场",
]

_LLM_PROTECTED_SLOTS = frozenset(["scene", "constraint"])

_LLM_POLISH_CONSTRAINTS = [
    "只允许优化语句顺滑度，不得新增语义",
    "不得删除硬性视觉约束",
    "不得改动场景、人物、风格主干信息",
    "不得删除或替换原有的约束性词语（如：稳定、统一、连续、不跳变）",
    "输出保持简短、自然、面向视频模型理解",
]

_LLM_POLISH_SYSTEM = (
    "你是一名视频提示词润色助手。"
    "你的任务仅是把输入片段润色得更顺，不允许新增语义，不允许删减硬约束。"
    "只输出润色后的片段本身。"
)

CLAUSE_SPLIT_RE = re.compile(r"[；;。！？\n]+")
_CJK_CHAR_RE = re.compile(
    "[一-鿟㐀-䶿豈-﫿"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f"
    "\U0002b740-\U0002b81f\U0002b820-\U0002ceaf"
    "\U0002ceb0-\U0002ebe0\U00030000-\U0003134f"
    r"]+"
)


# ── Public utilities ─────────────────────────────────────────────────────────


def contains_cjk(text: str) -> bool:
    """Check whether *text* contains any CJK character (full range Ext A–G)."""
    return bool(_CJK_CHAR_RE.search(text or ""))


def extract_cjk_ranges(text: str) -> list[str]:
    """Extract contiguous CJK strings from *text*."""
    return _CJK_CHAR_RE.findall(text or "")


# ── Text helpers ─────────────────────────────────────────────────────────────


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _slot_hits_from_text(text: str, *, target: str = "video") -> list[str]:
    value = _clean_text(text)
    if not value:
        return []
    whitelist = _get_whitelist(target)
    matched: list[str] = []
    for slot, keywords in whitelist.items():
        if _contains_any(value, keywords):
            matched.append(slot)
    return matched


def _score_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio() * 100.0


def _get_whitelist(target: str) -> dict[str, list[str]]:
    return VIDEO_WHITELIST if target == "video" else REF_WHITELIST


def _get_blacklist(target: str) -> list[str]:
    return VIDEO_BLACKLIST if target == "video" else REF_BLACKLIST


def _style_phrase_priority(text: str) -> int:
    value = _clean_text(text)
    best = 0
    for keyword, weight in STYLE_PRIORITY.items():
        if keyword in value:
            best = max(best, weight)
    if best:
        return best
    if "古风" in value or "仙侠" in value:
        return 96
    if "电影感" in value:
        return 88
    if "文旅" in value or "大片" in value:
        return 80
    if "文艺" in value or "留白" in value:
        return 70
    return 0


def _is_anchor_phrase(text: str) -> bool:
    return _contains_any(_clean_text(text), _NO_MERGE_ANCHORS)


# ── Clause extraction ────────────────────────────────────────────────────────


def _extract_candidate_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    for chunk in CLAUSE_SPLIT_RE.split(_clean_text(text)):
        value = chunk.strip(" ，、,.；;：:")
        if not value:
            continue
        if len(value) > 64:
            parts = re.split(r"[，、,]", value)
            for part in parts:
                part = part.strip()
                if 3 <= len(part) <= 48:
                    clauses.append(part)
        elif len(value) >= 3:
            clauses.append(value)
    return clauses


def _extract_visual_clauses(text: str, *, target: str = "video") -> list[str]:
    blacklist = _get_blacklist(target)
    clauses: list[str] = []
    for clause in _extract_candidate_clauses(text):
        has_visual = bool(_slot_hits_from_text(clause, target=target))
        if not has_visual:
            continue
        if _contains_any(clause, META_BLACKLIST) or _contains_any(clause, AUDIO_BLACKLIST):
            continue
        if _contains_any(clause, blacklist) and not _contains_any(clause, ["构图", "服化道", "色调", "光影"]):
            continue
        clauses.append(clause)
    return clauses


# ── Slot classification ──────────────────────────────────────────────────────


def classify_slot_with_confidence(text: str, *, target: str = "video") -> list[tuple[str, float]]:
    """Weighted keyword scorer — deterministic and inspectable."""
    value = _clean_text(text)
    if not value:
        return []
    whitelist = _get_whitelist(target)
    scores: dict[str, float] = {}
    for slot, keywords in whitelist.items():
        hits = sum(1 for keyword in keywords if keyword in value)
        if hits:
            scores[slot] = min(1.0, 0.25 + hits * 0.2)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def classify_slot_best(text: str, *, min_confidence: float = 0.5, target: str = "video") -> str | None:
    ranked = classify_slot_with_confidence(text, target=target)
    if not ranked:
        return None
    slot, confidence = ranked[0]
    if confidence < min_confidence:
        return None
    return slot


def _preferred_slot_for_clause(clause: str, *, target: str = "video") -> str | None:
    """Map a visual clause to its best slot.

    Uses keyword heuristics first, then falls back to ``classify_slot_best``.
    ``classify_slot_best`` is imported via deferred local reference to avoid
    any runtime forward-reference confusion — though Python resolves it
    at call time, not definition time.
    """
    value = _clean_text(clause)
    if not value:
        return None
    if value.startswith("运镜") or "转场" in value or "过渡" in value:
        return "camera"
    if value.startswith("节奏"):
        return "camera"
    if value.startswith("光影") or "逆光" in value or "柔光" in value:
        return "lighting"
    if value.startswith("色调") or "影调" in value or "色温" in value:
        return "color"
    if value.startswith("构图") or "透视" in value or "空间" in value:
        return "constraint"
    if value.startswith("禁用") or value.startswith("避免"):
        return "constraint"
    if value.startswith("人物") or "仪态" in value or "服化道" in value:
        return "character"
    return classify_slot_best(value, target=target)


# ── Slot normalization ───────────────────────────────────────────────────────


def _normalize_slot_hints(source: dict[str, Any], *, target: str = "video") -> dict[str, list[str]]:
    raw = source.get("slot_hints", {}) or {}
    if not isinstance(raw, dict):
        return {}
    allowed = set(SLOT_ORDER)
    normalized: dict[str, list[str]] = {}
    for slot, phrases in raw.items():
        if slot not in allowed or not isinstance(phrases, list):
            continue
        cleaned = [_clean_text(phrase) for phrase in phrases if _clean_text(phrase)]
        if cleaned:
            normalized[slot] = cleaned
    return normalized


def _compact_phrase_from_source(source: dict[str, Any], slot: str) -> str:
    name = _clean_text(source.get("name", ""))
    text = _clean_text(source.get("prompt_text", ""))
    combined = f"{name} {text}"
    if slot == "style":
        if "古风" in combined or "仙侠" in combined:
            return "古风仙侠电影感"
        if "文旅" in combined or "大片" in combined:
            return "大景别山河电影质感"
        if "文艺" in combined or "留白" in combined:
            return "克制留白的文艺气质"
        if "电影感" in combined:
            return "电影级画面质感"
    if slot == "camera":
        if "转场" in combined:
            return "镜头转场自然顺滑"
        if "运镜" in combined:
            return "运镜稳定连贯"
        if "航拍" in combined:
            return "大景别航拍运镜"
        if "远景" in combined and "中景" in combined:
            return "远中近景切换清晰"
        if "远景" in combined:
            return "大远景构图"
        if "中景" in combined:
            return "中景人物构图"
    if slot == "mood":
        if "宿命" in combined:
            return "清冷宿命感"
        if "氛围" in combined or "意境" in combined:
            return "氛围浓郁，情绪递进清晰"
    if slot == "character":
        if "服化道" in combined:
            return "服化道统一"
        if "人物" in combined or "五官" in combined:
            return "人物五官稳定"
        if "仪态" in combined:
            return "人物仪态克制"
    if slot == "lighting":
        if "光" in combined:
            return "光影层次统一"
    if slot == "color":
        if "色调" in combined or "色彩" in combined or "影调" in combined:
            return "色调统一稳定"
    if slot == "constraint":
        if "构图" in combined or "透视" in combined or "空间" in combined:
            return "构图清晰，空间透视稳定"
        if "稳定" in combined or "连续" in combined or "统一" in combined:
            return "角色与场景连续稳定"
    return ""


# ── Source filtering ─────────────────────────────────────────────────────────


def filter_visual_sources(sources: list[dict[str, Any]], *, target: str = "video") -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for source in sources:
        name_text = _clean_text(source.get("name", ""))
        prompt_text = _clean_text(source.get("prompt_text", ""))
        slot_hints = _normalize_slot_hints(source, target=target)
        name_slots = _slot_hits_from_text(name_text, target=target)
        visual_clauses = _extract_visual_clauses(prompt_text, target=target)
        if not visual_clauses and not slot_hints and _contains_any(name_text, _get_blacklist(target) + AUDIO_BLACKLIST):
            continue
        clause_slots: list[str] = []
        for clause in visual_clauses:
            clause_slots.extend(_slot_hits_from_text(clause, target=target))
        hint_slots = list(slot_hints.keys())
        matched_slots = list(dict.fromkeys(hint_slots + name_slots + clause_slots))
        if not matched_slots:
            continue
        enriched = dict(source)
        enriched["allowed_slots"] = matched_slots
        enriched["slot_hints"] = slot_hints
        enriched["visual_prompt_text"] = "；".join(visual_clauses)
        filtered.append(enriched)
    return filtered


# ── Deduplication ────────────────────────────────────────────────────────────


def dedupe_phrases(phrases: list[str], *, threshold: float = 88.0) -> list[str]:
    unique: list[str] = []
    for phrase in phrases:
        text = _clean_text(phrase)
        if not text:
            continue
        if any(_score_similarity(text, kept) >= threshold for kept in unique):
            continue
        unique.append(text)
    return unique


# ── Style conflict resolution ────────────────────────────────────────────────


def _resolve_style_conflicts(phrases: list[str]) -> list[str]:
    ranked = sorted(dedupe_phrases(phrases), key=lambda item: (_style_phrase_priority(item), len(item)), reverse=True)
    if not ranked:
        return []
    main = ranked[:1]
    supports: list[str] = []
    for phrase in ranked[1:]:
        if len(supports) >= 2:
            break
        if all(_score_similarity(phrase, kept) < 80 for kept in main + supports):
            supports.append(phrase)
    return main + supports


# ── Slot normalization (main) ────────────────────────────────────────────────


def normalize_sources_to_slots(
    sources: list[dict[str, Any]],
    *,
    scene_heading: str = "",
    shot_text: str = "",
    target: str = "video",
) -> dict[str, list[str]]:
    slots: dict[str, list[str]] = {slot: [] for slot in SLOT_ORDER}
    if scene_heading:
        slots["scene"].append(_clean_text(scene_heading))
    if shot_text:
        slots["scene"].extend(_extract_candidate_clauses(shot_text)[:3])

    for source in sources:
        if "visual_prompt_text" in source:
            prompt_text = _clean_text(source.get("visual_prompt_text", ""))
        else:
            prompt_text = _clean_text(source.get("prompt_text", ""))
        name_text = _clean_text(source.get("name", ""))
        slot_hints = _normalize_slot_hints(source, target=target)
        if not prompt_text and not name_text:
            continue
        for slot, phrases in slot_hints.items():
            slots[slot].extend(phrases)
        if slot_hints:
            continue
        allowed_slots = list(dict.fromkeys(list(source.get("allowed_slots", []) or []) + list(slot_hints.keys())))
        primary_slot = (
            classify_slot_best(name_text, target=target)
            or (next(iter(slot_hints.keys())) if slot_hints else None)
            or (allowed_slots[0] if allowed_slots else None)
            or classify_slot_best(prompt_text, target=target)
            or "constraint"
        )

        compact_phrase = _compact_phrase_from_source(source, primary_slot)
        if compact_phrase:
            slots[primary_slot].append(compact_phrase)

        for clause in _extract_candidate_clauses(prompt_text):
            if len(clause) > 40:
                continue
            matched_slot = _preferred_slot_for_clause(clause, target=target) or primary_slot
            slots[matched_slot].append(clause)

    for slot, values in slots.items():
        if slot == "style":
            slots[slot] = _resolve_style_conflicts(values)
        elif slot == "scene":
            slots[slot] = dedupe_phrases(values)
        else:
            slots[slot] = dedupe_phrases(values)
    return slots


def _trim_slot(phrases: list[str], limit: int) -> list[str]:
    return [phrase for phrase in phrases if phrase][:limit]


def render_normalized_prose(slots: dict[str, list[str]], *, target: str = "video") -> str:
    pieces: list[str] = []
    scene_phrases = _trim_slot(slots.get("scene", []), 3)
    if scene_phrases:
        pieces.append(f"场景画面：{'，'.join(scene_phrases)}")
    style_phrases = _trim_slot(slots.get("style", []), 3)
    if style_phrases:
        pieces.append(f"整体风格：{'，'.join(style_phrases)}")
    camera_phrases = _trim_slot(slots.get("camera", []), 3)
    if camera_phrases:
        pieces.append(f"镜头语言：{'，'.join(camera_phrases)}")
    mood_phrases = _trim_slot(slots.get("mood", []), 3)
    if mood_phrases:
        pieces.append(f"氛围情绪：{'，'.join(mood_phrases)}")
    character_phrases = _trim_slot(slots.get("character", []), 3)
    if character_phrases:
        pieces.append(f"人物表现：{'，'.join(character_phrases)}")
    lighting_phrases = _trim_slot(slots.get("lighting", []), 2)
    if lighting_phrases:
        pieces.append(f"光影要求：{'，'.join(lighting_phrases)}")
    color_phrases = _trim_slot(slots.get("color", []), 2)
    if color_phrases:
        pieces.append(f"色调要求：{'，'.join(color_phrases)}")
    constraint_phrases = _trim_slot(slots.get("constraint", []), 4)
    if constraint_phrases:
        label = "画面约束" if target == "video" else "参考图约束"
        pieces.append(f"{label}：{'，'.join(constraint_phrases)}")
    return "。".join(piece for piece in pieces if piece).strip("。") + ("。" if pieces else "")


# ── LLM polishing ────────────────────────────────────────────────────────────


def polish_phrase_with_llm(
    phrase: str,
    *,
    client: Any = None,
    model: str = "doubao-pro-32k",
    max_tokens: int = 64,
) -> str:
    if client is None or not phrase:
        return phrase
    if _is_anchor_phrase(phrase):
        return phrase
    constraint_block = "；".join(_LLM_POLISH_CONSTRAINTS)
    prompt = f"原句：{phrase}\n约束：{constraint_block}"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _LLM_POLISH_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        result = _clean_text(resp.choices[0].message.content)
        if not result:
            return phrase
        for anchor in _NO_MERGE_ANCHORS:
            if anchor in phrase and anchor not in result:
                return phrase
        if _contains_any(result, VIDEO_BLACKLIST):
            return phrase
        return result
    except Exception:
        return phrase


def polish_prose_with_llm(
    prose: str,
    *,
    client: Any = None,
    model: str = "doubao-pro-32k",
) -> str:
    if not prose or client is None:
        return prose
    parts = re.split(r"(。)", prose)
    polished: list[str] = []
    protected_prefixes = ("场景画面：", "画面约束：", "参考图约束：")
    for part in parts:
        text = _clean_text(part)
        if not text or text == "。":
            polished.append(part)
            continue
        if any(text.startswith(prefix) for prefix in protected_prefixes):
            polished.append(part)
            continue
        # Strip label prefix before sending to LLM, re-attach after.
        # Prevents LLM from eating the structural label (e.g. "整体风格：").
        label_prefix = ""
        content = text
        colon_pos = text.find("：")
        if colon_pos != -1 and colon_pos <= 6:
            label_prefix = text[: colon_pos + 1]
            content = text[colon_pos + 1:]
        polished_content = polish_phrase_with_llm(content, client=client, model=model) if content else content
        polished.append(label_prefix + polished_content)
    return "".join(polished)


def polish_slots_with_llm(
    slots: dict[str, list[str]],
    *,
    client: Any = None,
    model: str = "doubao-pro-32k",
    skip_slots: list[str] | None = None,
) -> dict[str, list[str]]:
    skip = _LLM_PROTECTED_SLOTS | set(skip_slots or [])
    result: dict[str, list[str]] = {}
    for slot, phrases in slots.items():
        if slot in skip:
            result[slot] = phrases
            continue
        result[slot] = [polish_phrase_with_llm(phrase, client=client, model=model) if len(phrase) > 8 else phrase for phrase in phrases]
    return result
