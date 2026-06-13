"""Hard checks for production text that must affect generation.

Vague style words are allowed as secondary modifiers, but they cannot be the
only payload sent into script, storyboard, reference-image, keyframe, or video
generation.
"""

from __future__ import annotations

import re
from typing import Any


VAGUE_STYLE_TERMS = (
    "电影感",
    "高级",
    "高级感",
    "质感",
    "氛围",
    "氛围感",
    "稳定",
    "统一",
    "节奏",
    "留白",
    "克制",
    "自然",
    "真实",
    "精致",
    "光影",
    "大片感",
)

CONCRETE_ANCHOR_TERMS = (
    "张嘉益",
    "电视剧主角",
    "中年",
    "男人",
    "女人",
    "男主",
    "女主",
    "顾客",
    "店员",
    "警察",
    "医生",
    "父亲",
    "母亲",
    "派出所",
    "调解室",
    "医院",
    "办公室",
    "客厅",
    "街道",
    "金店",
    "柜台",
    "文件袋",
    "文件",
    "饭盒",
    "工牌",
    "病历",
    "欠条",
    "黄金",
    "首饰",
    "戒指",
    "项链",
    "推门",
    "坐下",
    "递交",
    "攥着",
    "抬眼",
    "转身",
    "停住",
    "走进",
    "拿出",
)

GENERIC_PLACEHOLDER_TERMS = (
    "主角",
    "核心场景",
    "关键道具",
    "关键信息",
    "人物关系",
    "空间关系",
    "情绪变化",
    "动作明确",
)


def analyze_production_text_effectiveness(text: Any, *, domain: str = "generation") -> dict[str, Any]:
    value = str(text or "").strip()
    compact = re.sub(r"\s+", "", value)
    vague_hits = [term for term in VAGUE_STYLE_TERMS if term in compact]
    concrete_hits = [term for term in CONCRETE_ANCHOR_TERMS if term in compact]
    placeholder_hits = [term for term in GENERIC_PLACEHOLDER_TERMS if term in compact]
    named_person_hits = re.findall(r"[\u4e00-\u9fff]{2,4}(?:演的|饰演|主演)", compact)
    has_specific_number = bool(re.search(r"\d+|[一二三四五六七八九十]个|[一二三四五六七八九十]名", compact))
    effective_anchor_count = len(set(concrete_hits)) + len(named_person_hits) + (1 if has_specific_number else 0)
    vague_only = bool(vague_hits) and effective_anchor_count == 0
    placeholder_only = len(placeholder_hits) >= 2 and effective_anchor_count == 0
    too_short = len(compact) < 8
    ok = bool(compact) and not too_short and not vague_only and not placeholder_only
    if domain in {"reference_image", "keyframe", "storyboard"}:
        ok = ok and effective_anchor_count > 0
    reasons: list[str] = []
    if not compact:
        reasons.append("empty_text")
    if too_short:
        reasons.append("too_short")
    if vague_only:
        reasons.append("vague_style_only")
    if placeholder_only:
        reasons.append("generic_placeholder_only")
    if domain in {"reference_image", "keyframe", "storyboard"} and effective_anchor_count == 0:
        reasons.append("missing_concrete_anchor")
    return {
        "ok": ok,
        "domain": domain,
        "reasons": reasons,
        "vague_terms": vague_hits,
        "concrete_terms": concrete_hits,
        "placeholder_terms": placeholder_hits,
        "effective_anchor_count": effective_anchor_count,
    }


def assert_production_text_effective(text: Any, *, domain: str = "generation") -> dict[str, Any]:
    report = analyze_production_text_effectiveness(text, domain=domain)
    if not report["ok"]:
        raise ValueError(
            "Production text is not actionable: "
            + ", ".join(report["reasons"] or ["unknown"])
        )
    return report
