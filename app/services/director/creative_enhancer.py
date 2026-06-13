from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


RULE_FILE = Path(__file__).resolve().parent / "rules" / "creative_enhancer_v1.json"


@dataclass(frozen=True)
class DimensionRule:
    id: str
    label: str
    weight: float
    threshold: int
    action: str


def _safe_score(base: int) -> int:
    return max(0, min(100, int(base)))


@lru_cache(maxsize=1)
def load_enhancer_rules() -> dict[str, Any]:
    with RULE_FILE.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    raw["dimensions"] = [
        DimensionRule(
            id=str(item.get("id", "")),
            label=str(item.get("label", "")),
            weight=float(item.get("weight", 0)),
            threshold=int(item.get("threshold", 70)),
            action=str(item.get("action", "")),
        )
        for item in raw.get("dimensions", [])
    ]
    return raw


def enhance_user_input(message: str, history_context: str = "") -> dict[str, Any]:
    rules = load_enhancer_rules()
    structure = list(rules.get("structure", []))

    intent = str(message or "").strip()
    history = str(history_context or "").strip()
    if not intent:
        return {"enhanced_message": "", "anchors": {}, "structure": structure}

    anchors = {
        "人物锚点": "主角年龄/职业/外观/口吻/弱点",
        "场景锚点": "时间/地点/空间关系/关键道具",
        "商业锚点": "卖点触达时机/信任背书/转化动作",
        "执行锚点": "景别/机位/运镜/光线/节奏",
    }
    scaffold = (
        "请按短剧导演标准执行：\n"
        f"结构骨架：{'→'.join(structure)}\n"
        "输出要求：\n"
        "1) 前3秒必须有钩子\n"
        "2) 每15秒至少有一个情绪或信息兑现点\n"
        "3) 明确人物/场景/道具连续性\n"
        "4) 镜头可执行，避免抽象空话\n"
    )
    anchor_text = "\n".join([f"- {k}：{v}" for k, v in anchors.items()])
    history_block = f"对话上下文：{history}\n" if history else ""
    enhanced = f"{history_block}用户需求：{intent}\n\n{scaffold}\n连续性锚点：\n{anchor_text}"
    return {"enhanced_message": enhanced, "anchors": anchors, "structure": structure}


def evaluate_v1_draft(v1_text: str, original_message: str = "") -> dict[str, Any]:
    rules = load_enhancer_rules()
    dims: list[DimensionRule] = rules.get("dimensions", [])
    text = str(v1_text or "")
    msg = str(original_message or "")

    # Heuristic signals for rule-first scoring.
    has_hook = any(k in text for k in ("但是", "却", "突然", "没想到", "第一秒", "开场"))
    has_character = any(k in text for k in ("主角", "女主", "男主", "角色", "人物"))
    has_scene = any(k in text for k in ("场景", "门店", "街道", "室内", "室外"))
    has_camera = any(k in text for k in ("特写", "近景", "中景", "远景", "机位", "运镜"))
    has_dialogue = any(k in text for k in ("：", "“", "台词", "对白"))
    has_suspense = any(k in text for k in ("悬念", "反转", "伏笔", "下一步"))
    has_market_tag = any(k in msg + text for k in ("短剧", "广告", "转化", "种草", "爆点"))
    length_factor = min(len(text), 1200) / 1200.0

    raw_score_map = {
        "hook_strength": _safe_score(52 + (24 if has_hook else 0) + int(12 * length_factor)),
        "highlight_density": _safe_score(54 + int(20 * length_factor)),
        "pace_rhythm": _safe_score(50 + (18 if has_camera else 0) + int(18 * length_factor)),
        "continuity": _safe_score(48 + (14 if has_character else 0) + (14 if has_scene else 0) + int(14 * length_factor)),
        "character_appeal": _safe_score(52 + (20 if has_character else 0) + int(12 * length_factor)),
        "dialogue_quality": _safe_score(50 + (20 if has_dialogue else 0) + int(14 * length_factor)),
        "suspense_effectiveness": _safe_score(48 + (24 if has_suspense else 0) + int(12 * length_factor)),
        "market_fit": _safe_score(50 + (22 if has_market_tag else 0) + int(10 * length_factor)),
    }

    dim_results: list[dict[str, Any]] = []
    total = 0.0
    improvements: list[str] = []

    for d in dims:
        score = raw_score_map.get(d.id, 60)
        passed = score >= d.threshold
        total += score * d.weight
        dim_results.append(
            {
                "id": d.id,
                "label": d.label,
                "score": score,
                "threshold": d.threshold,
                "passed": passed,
                "weight": d.weight,
                "action": d.action,
            }
        )
        if not passed:
            improvements.append(f"{d.label}：{d.action}")

    return {
        "version": rules.get("version", "creative_enhancer_v1"),
        "total": _safe_score(round(total)),
        "dimensions": dim_results,
        "improvement_points": improvements,
        "needs_polish": len(improvements) > 0,
    }


def build_polish_block(report: dict[str, Any]) -> str:
    points = report.get("improvement_points", []) if isinstance(report, dict) else []
    if not points:
        return ""
    return "【可打磨点】\n" + "\n".join([f"- {p}" for p in points[:6]])
