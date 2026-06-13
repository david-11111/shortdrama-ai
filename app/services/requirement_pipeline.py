from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.config import get_settings
from app.services.prompt.engine import retrieve_prompt_matches
from app.services.story_understanding import build_story_understanding


logger = logging.getLogger(__name__)


PRODUCT_AD_TERMS = ("广告", "TVC", "品牌", "产品", "电商", "宣传片", "种草", "美妆", "首饰", "珠宝", "睫毛")


async def build_requirement_pipeline(
    instruction: str,
    *,
    project_context: dict[str, Any] | None = None,
    llm_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    raw_instruction = str(instruction or "").strip()
    project_context = project_context or {}
    settings = get_settings()
    timeout_seconds = _coerce_timeout(
        llm_timeout_seconds
        if llm_timeout_seconds is not None
        else getattr(settings, "requirement_llm_timeout_seconds", 8.0)
    )
    local = _local_requirement_card(raw_instruction)
    source = "local_fallback"
    llm_error = ""
    try:
        llm_card = await asyncio.wait_for(
            _call_doubao_requirement_card(
                raw_instruction,
                project_context=project_context,
                timeout_seconds=timeout_seconds,
            ),
            timeout=timeout_seconds,
        )
        card = _merge_requirement_card(local["understanding_card"], llm_card)
        source = "doubao"
    except TimeoutError:
        logger.warning("Doubao requirement first pass timed out after %.1fs; using local fallback", timeout_seconds)
        card = local["understanding_card"]
        llm_error = f"timeout after {timeout_seconds:.1f}s"
    except Exception as exc:
        logger.warning("Doubao requirement first pass failed; using local fallback: %s", exc)
        card = local["understanding_card"]
        llm_error = str(exc)

    demand_type = _normalize_demand_type(card.get("demand_type") or local.get("demand_type"))
    card["demand_type"] = demand_type
    missing_fields = _missing_fields_for_card(card)
    library_context = _retrieve_library_context(raw_instruction, card)
    return {
        "version": "requirement_pipeline_v1",
        "raw_instruction": raw_instruction,
        "source": source,
        "llm_error": llm_error,
        "demand_type": demand_type,
        "initial_brief": str(card.get("initial_brief") or raw_instruction),
        "mentions_real_work": bool(local.get("mentions_real_work")),
        "entity_resolution": local.get("entity_resolution") or {},
        "missing_fields": missing_fields,
        "sufficient_for_storyboard": not missing_fields,
        "understanding_card": card,
        "library_context": library_context,
    }


async def _call_doubao_requirement_card(
    instruction: str,
    *,
    project_context: dict[str, Any],
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not (settings.doubao_api_keys or settings.ark_api_keys):
        raise RuntimeError("doubao_api_key_not_configured")

    from app.services.doubao import generate_text
    from app.services.key_pool import key_pool

    system_prompt = (
        "你是 SaaS 视频生产链路的需求理解助手。"
        "只做需求理解，不写完整分镜。"
        "请把用户一句话解析成严格 JSON，字段："
        "initial_brief, demand_type, subject, selling_points, audience, "
        "visual_anchors, prop_anchors, action_anchors, tone_anchors, must_not, missing_fields。"
        "demand_type 只能是 product_ad, short_drama, real_work_remake, tutorial, ecommerce_showcase。"
        "广告、品牌、产品宣传、美妆、首饰、电商种草必须归为 product_ad 或 ecommerce_showcase。"
    )
    prompt = json.dumps(
        {"instruction": instruction, "project_context": project_context},
        ensure_ascii=False,
        default=str,
    )
    key_name, api_key = key_pool.acquire("doubao")
    try:
        result = await asyncio.to_thread(
            generate_text,
            api_key,
            {
                "system_prompt": system_prompt,
                "prompt": prompt,
                "temperature": 0.1,
                "max_tokens": 900,
                "timeout_seconds": _coerce_timeout(timeout_seconds),
            },
            timeout_seconds=_coerce_timeout(timeout_seconds),
        )
    finally:
        key_pool.release(key_name)
    return _parse_json_object(result.get("text", ""))


def _local_requirement_card(instruction: str) -> dict[str, Any]:
    story = build_story_understanding(instruction)
    demand_type = "product_ad" if _is_product_ad(instruction) else "short_drama"
    card = dict(story.get("understanding_card") or {})
    card.update(_local_product_ad_fields(instruction) if demand_type == "product_ad" else {})
    card.setdefault("initial_brief", instruction)
    card["demand_type"] = demand_type
    return {
        **story,
        "demand_type": demand_type,
        "understanding_card": card,
    }


def _local_product_ad_fields(instruction: str) -> dict[str, Any]:
    subject = _subject_from_instruction(instruction)
    visual = []
    actions = []
    props = []
    tones = []
    if "睫毛" in instruction:
        props.extend(["睫毛膏", "睫毛夹", "镜子"])
        visual.extend(["眼部微距", "睫毛根根分明", "睫毛卷翘效果"])
        actions.extend(["涂睫毛膏", "夹睫毛", "展示睫毛效果"])
        tones.extend(["高级美妆质感", "柔光", "干净奢华"])
    if any(term in instruction for term in ("黄金", "首饰", "珠宝", "金饰")):
        props.extend(["黄金首饰", "首饰盒", "镜面台面"])
        visual.extend(["产品微距", "金属高光", "反光细节", "佩戴效果"])
        actions.extend(["佩戴首饰", "旋转展示", "展示产品细节"])
        tones.extend(["轻奢", "高级", "精致", "光影质感"])
    if "微距" in instruction:
        visual.append("近景微距")
    if "柔光" in instruction:
        tones.append("柔光")
    if "高级" in instruction:
        tones.append("高级质感")
    return {
        "subject": subject,
        "selling_points": _dedupe(["产品质感", "可见效果"]),
        "visual_anchors": _dedupe(visual or ["产品特写", "使用效果展示"]),
        "prop_anchors": _dedupe(props or [subject]),
        "action_anchors": _dedupe(actions or ["展示产品", "使用产品", "效果呈现"]),
        "tone_anchors": _dedupe(tones or ["商业广告质感", "干净高级"]),
        "must_not": ["不要短剧冲突", "不要对手方施压", "不要电视剧质感", "不要让人物抢产品重心"],
        "missing_fields": [],
    }


def _retrieve_library_context(instruction: str, card: dict[str, Any]) -> dict[str, Any]:
    query_parts = [
        instruction,
        str(card.get("initial_brief") or ""),
        str(card.get("subject") or ""),
        " ".join(
            item
            for key in ("selling_points", "visual_anchors", "prop_anchors", "action_anchors", "tone_anchors")
            for item in _list(card.get(key))
        ),
    ]
    query = " ".join(part for part in query_parts if part).strip()
    try:
        package = retrieve_prompt_matches(query, stage="script", top_k=6, global_context=query)
        matched = package.get("matched") or []
    except Exception as exc:
        logger.warning("Requirement prompt-library retrieval failed: %s", exc)
        matched = []
    prompt_lines = []
    for item in matched[:6]:
        name = str(item.get("name") or item.get("title") or "")
        prompt_text = str(item.get("prompt_text") or "")
        if name or prompt_text:
            prompt_lines.append(f"{name}: {prompt_text[:260]}")
    return {
        "query": query,
        "matched": matched,
        "matched_names": [str(item.get("name") or item.get("title") or "") for item in matched if item.get("name") or item.get("title")],
        "prompt_block": "\n".join(prompt_lines),
    }


def _merge_requirement_card(local_card: dict[str, Any], llm_card: dict[str, Any]) -> dict[str, Any]:
    merged = dict(local_card)
    normalized = _normalize_llm_card(llm_card)
    for key, value in normalized.items():
        if isinstance(value, list):
            if value:
                merged[key] = value
        elif str(value or "").strip():
            merged[key] = value
    return merged


def _normalize_llm_card(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "initial_brief": _scalar(value.get("initial_brief") or value.get("brief")),
        "demand_type": _normalize_demand_type(value.get("demand_type") or value.get("type")),
        "subject": _scalar(value.get("subject") or value.get("product") or value.get("topic")),
        "selling_points": _list(value.get("selling_points")),
        "audience": _scalar(value.get("audience")),
        "visual_anchors": _list(value.get("visual_anchors") or value.get("scene_anchors")),
        "prop_anchors": _list(value.get("prop_anchors")),
        "action_anchors": _list(value.get("action_anchors")),
        "tone_anchors": _list(value.get("tone_anchors")),
        "must_not": _list(value.get("must_not")),
        "missing_fields": _list(value.get("missing_fields")),
    }


def _missing_fields_for_card(card: dict[str, Any]) -> list[str]:
    if card.get("missing_fields"):
        return _list(card.get("missing_fields"))
    required = ("subject", "visual_anchors", "action_anchors", "tone_anchors")
    if card.get("demand_type") == "product_ad":
        return [field for field in required if not card.get(field)]
    return []


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.removeprefix("json").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _normalize_demand_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"product_ad", "short_drama", "real_work_remake", "tutorial", "ecommerce_showcase"}:
        return normalized
    if normalized in {"ad", "advertising", "commercial", "tvc", "brand"}:
        return "product_ad"
    return "short_drama"


def _is_product_ad(text: str) -> bool:
    return any(term.lower() in str(text or "").lower() for term in PRODUCT_AD_TERMS)


def _subject_from_instruction(text: str) -> str:
    value = str(text or "").strip()
    for suffix in ("广告视频", "广告片", "广告", "宣传片", "种草视频"):
        if suffix in value:
            prefix = value.split(suffix, 1)[0].strip(" ，,。")
            if prefix:
                return f"{prefix}{suffix}".strip()
    return value[:24] or "产品广告"


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "，".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip() for part in value.replace("/", "，").split("，")]
    elif isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value]
    else:
        items = [str(value).strip()]
    return _dedupe([item for item in items if item])


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def _coerce_timeout(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 8.0
    return max(0.1, min(parsed, 30.0))
