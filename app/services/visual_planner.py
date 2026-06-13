"""Visual asset planning for director production.

The first version is intentionally data-driven. It does not dispatch image
generation jobs; it turns preflight missing references into concrete asset
actions and pairs them with existing reference candidates when available.
"""

from __future__ import annotations

import re
from typing import Any


CANONICAL_ASSET_KINDS = {
    "character",
    "scene",
    "prop",
    "costume",
    "style",
    "golden_reference",
    "shot_keyframe",
    "source_video",
    "video_clip",
}

PLANNABLE_REF_KINDS = ("character", "scene", "prop", "costume", "style")

KIND_LABELS = {
    "character": "角色",
    "scene": "场景",
    "prop": "道具",
    "costume": "服化道",
    "style": "风格",
    "shot_keyframe": "分镜关键帧",
    "video_clip": "视频片段",
}

REF_FIELDS = {
    "character": "character_refs",
    "scene": "scene_refs",
    "prop": "prop_refs",
    "costume": "costume_refs",
    "style": "style_refs",
}

REF_JSON_FIELDS = {
    "character": "character_refs_json",
    "scene": "scene_refs_json",
    "prop": "prop_refs_json",
    "costume": "costume_refs_json",
    "style": "style_refs_json",
}

KIND_ALIASES = {
    "character_ref": "character",
    "person": "character",
    "role": "character",
    "scene_ref": "scene",
    "location": "scene",
    "environment": "scene",
    "prop_ref": "prop",
    "object": "prop",
    "costume_ref": "costume",
    "makeup": "costume",
    "style_ref": "style",
    "golden_reference": "golden_reference",
    "keyframe": "shot_keyframe",
    "shot": "shot_keyframe",
    "image": "shot_keyframe",
    "source_video": "source_video",
    "video": "video_clip",
}

SCENE_HINTS = (
    "外景", "内景", "房间", "办公室", "街", "车内", "山", "谷", "祭坛", "家", "殿",
    "军营", "客厅", "卧室", "医院", "学校", "工厂", "仓库", "餐厅", "夜景", "雨夜",
    "金店", "柜台", "门店", "展厅",
)
PROP_HINTS = (
    "剑", "刀", "枪", "玉佩", "合同", "手机", "车", "戒指", "信", "文件", "法阵",
    "药", "酒杯", "钥匙", "箱", "产品", "道具", "黄金", "金饰", "手镯", "项链",
    "电子秤", "报价单",
)
STYLE_HINTS = (
    "电影感", "古风", "仙侠", "悬疑", "写实", "赛博", "复古", "冷色", "暖色",
    "高饱和", "低饱和", "TVC", "广告", "短剧", "商业", "品牌",
)
CHARACTER_HINTS = ("人", "她", "他", "男人", "女人", "主角", "女主", "男主", "将领", "少年", "老人", "顾客", "店员")
COSTUME_HINTS = ("制服", "西装", "工装", "手套", "服装", "妆造", "造型")


def normalize_asset_kind(value: Any, *, fallback: str = "shot_keyframe") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return fallback
    raw = raw.replace("-", "_").replace(" ", "_")
    if raw in CANONICAL_ASSET_KINDS:
        return raw
    return KIND_ALIASES.get(raw, fallback)


def default_lineage_metadata(
    metadata: dict[str, Any] | None,
    *,
    asset_type: str = "image",
    fallback_kind: str = "shot_keyframe",
) -> dict[str, Any]:
    base = dict(metadata or {})
    asset_kind = normalize_asset_kind(
        base.get("asset_kind") or base.get("entity_type") or base.get("kind") or asset_type,
        fallback=fallback_kind,
    )
    base.setdefault("asset_kind", asset_kind)
    base.setdefault("entity_type", asset_kind)
    source_kinds = {*PLANNABLE_REF_KINDS, "golden_reference", "source_video"}
    base.setdefault("lineage_role", "source" if asset_kind in source_kinds else "derived")
    base.setdefault("parent_asset_ids", [])
    base.setdefault("generation_method", base.get("generation_method") or "upload")
    base.setdefault("locked_traits", _default_locked_traits(asset_kind))
    return base


def build_planned_reference_metadata(action: dict[str, Any], *, asset_id: str) -> dict[str, Any]:
    kind = normalize_asset_kind(action.get("kind"), fallback="shot_keyframe")
    shot_index = action.get("shot_index")
    label = KIND_LABELS.get(kind, kind)
    metadata = {
        "asset_kind": kind,
        "entity_type": kind,
        "entity_id": f"shot-{shot_index}-{kind}",
        "entity_name": action.get("title") or f"待生成{label}参考",
        "lineage_role": "source",
        "generation_method": "planned_reference",
        "generation_status": "planned",
        "planning_action_id": action.get("id"),
        "source_shot_index": shot_index,
        "prompt_seed": action.get("prompt_seed") or "",
        "description": action.get("description") or "",
        "parent_asset_ids": [],
        "locked_traits": _default_locked_traits(kind),
    }
    metadata["planned_asset_id"] = asset_id
    return default_lineage_metadata(metadata, asset_type="image", fallback_kind=kind)


def build_visual_plan(shots: list[dict[str, Any]], assets: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_assets = [_normalize_asset(asset) for asset in assets]
    assets_by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in CANONICAL_ASSET_KINDS}
    for asset in normalized_assets:
        assets_by_kind.setdefault(asset["asset_kind"], []).append(asset)
    for shot in shots:
        selected_image = str(shot.get("selected_image") or "").strip()
        if not selected_image:
            continue
        assets_by_kind.setdefault("shot_keyframe", []).append({
            "asset_id": f"shot:{shot.get('shot_index') or shot.get('index')}",
            "asset_type": "image",
            "asset_kind": "shot_keyframe",
            "entity_type": "shot_keyframe",
            "entity_id": str(shot.get("shot_index") or shot.get("index") or ""),
            "entity_name": f"分镜 {shot.get('shot_index') or shot.get('index')}",
            "file_url": selected_image,
            "metadata": {"lineage_role": "derived", "shot_index": shot.get("shot_index") or shot.get("index")},
        })

    shot_plans = [_plan_shot(shot, assets_by_kind) for shot in shots]
    action_items = [action for plan in shot_plans for action in plan["action_items"]]
    seedream_budget = _build_seedream_budget(action_items, shots)
    summary = {
        kind: {
            "label": KIND_LABELS.get(kind, kind),
            "count": len(items),
            "ready": sum(1 for item in items if item.get("file_url")),
        }
        for kind, items in sorted(assets_by_kind.items())
    }
    risk_count = sum(1 for plan in shot_plans if plan["risk_level"] != "ready")
    return {
        "asset_summary": summary,
        "shot_plans": shot_plans,
        "asset_actions": action_items,
        "action_count": len(action_items),
        "risk_count": risk_count,
        "ready_count": len(shot_plans) - risk_count,
        "seedream_budget": seedream_budget,
    }


def _normalize_asset(asset: dict[str, Any]) -> dict[str, Any]:
    metadata = asset.get("metadata_json") or asset.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    asset_type = str(asset.get("asset_type") or "image")
    enriched = default_lineage_metadata(metadata, asset_type=asset_type)
    file_url = str(asset.get("file_url") or "")
    if not file_url:
        file_url = _primary_view_url(enriched)
    return {
        "asset_id": str(asset.get("asset_id") or asset.get("id") or ""),
        "asset_type": asset_type,
        "asset_kind": enriched["asset_kind"],
        "entity_type": enriched.get("entity_type") or enriched["asset_kind"],
        "entity_id": str(enriched.get("entity_id") or enriched.get("entity_name") or ""),
        "entity_name": str(enriched.get("entity_name") or enriched.get("filename") or ""),
        "file_url": file_url,
        "metadata": enriched,
    }


def _primary_view_url(metadata: dict[str, Any]) -> str:
    views = metadata.get("views")
    if not isinstance(views, dict):
        return ""
    primary = str(metadata.get("primary") or "")
    candidates = []
    if primary:
        candidates.append(views.get(primary))
    candidates.extend(views.values())
    for item in candidates:
        if isinstance(item, str) and item:
            return item
        if isinstance(item, dict):
            url = str(item.get("url") or item.get("file_url") or "")
            if url:
                return url
    return ""


def _plan_shot(shot: dict[str, Any], assets_by_kind: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    prompt = str(shot.get("prompt") or "")
    preflight = shot.get("director_preflight") if isinstance(shot.get("director_preflight"), dict) else {}
    preflight_required = _merge_kinds(
        _normalize_kind_list(preflight.get("required_refs")),
        _normalize_kind_list(preflight.get("missing_refs")),
    )
    required = preflight_required or _required_kinds(prompt)
    current = {
        "character": _as_list(shot.get("character_refs") or shot.get("character_refs_json")),
        "scene": _as_list(shot.get("scene_refs") or shot.get("scene_refs_json")),
        "prop": _as_list(shot.get("prop_refs") or shot.get("prop_refs_json")),
        "costume": _as_list(shot.get("costume_refs") or shot.get("costume_refs_json")),
        "style": _as_list(shot.get("style_refs") or shot.get("style_refs_json")),
        "shot_keyframe": [shot["selected_image"]] if shot.get("selected_image") else [],
    }
    missing = _merge_kinds(
        _normalize_kind_list(preflight.get("missing_refs")),
        [kind for kind in required if kind in PLANNABLE_REF_KINDS and not current.get(kind)],
    )
    recommendations = {
        kind: _recommend_assets(prompt, assets_by_kind.get(kind, []), current.get(kind, []))
        for kind in missing
    }
    action_items = [
        _build_action_item(shot, kind, prompt, recommendations.get(kind, []), preflight)
        for kind in missing
    ]
    score = _score(required, current, recommendations)
    risk_level = _risk_level(score, missing, action_items, preflight)
    return {
        "shot_index": shot.get("shot_index") or shot.get("index"),
        "prompt": prompt,
        "required_kinds": required,
        "current_refs": current,
        "missing_kinds": missing,
        "recommended_refs": recommendations,
        "action_items": action_items,
        "qa_score": score,
        "risk_level": risk_level,
        "suggestions": _suggestions(missing, recommendations, action_items),
        "preflight": preflight,
    }


def _required_kinds(prompt: str) -> list[str]:
    required = ["character", "scene", "style"]
    if _contains_any(prompt, PROP_HINTS):
        required.append("prop")
    if _contains_any(prompt, COSTUME_HINTS):
        required.append("costume")
    return _merge_kinds(required)


def _recommend_assets(prompt: str, assets: list[dict[str, Any]], existing: list[str]) -> list[dict[str, Any]]:
    if not assets:
        return []
    existing_set = set(existing)
    scored = []
    for asset in assets:
        if asset["asset_id"] in existing_set or asset["file_url"] in existing_set:
            continue
        haystack = " ".join(
            str(v)
            for v in (
                asset.get("entity_name"),
                asset.get("entity_id"),
                asset.get("asset_kind"),
                asset.get("metadata", {}).get("filename"),
                asset.get("metadata", {}).get("tags"),
            )
        )
        score = _token_overlap(prompt, haystack)
        scored.append((score, asset))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "asset_id": asset["asset_id"],
            "asset_kind": asset["asset_kind"],
            "entity_name": asset["entity_name"],
            "file_url": asset["file_url"],
            "match_score": score,
        }
        for score, asset in scored[:3]
    ]


def _build_action_item(
    shot: dict[str, Any],
    kind: str,
    prompt: str,
    recommendations: list[dict[str, Any]],
    preflight: dict[str, Any],
) -> dict[str, Any]:
    shot_index = shot.get("shot_index") or shot.get("index")
    label = KIND_LABELS.get(kind, kind)
    subject = _asset_subject(kind, prompt)
    has_candidate = bool(recommendations)
    action_type = "bind_existing" if has_candidate else "generate_reference"
    title = f"绑定已有{label}参考" if has_candidate else f"生成{subject}"
    description = (
        f"从推荐资产中选择一个{label}绑定到分镜 #{shot_index}。"
        if has_candidate
        else _action_description(kind, subject)
    )
    return {
        "id": f"shot-{shot_index}-{kind}",
        "shot_index": shot_index,
        "kind": kind,
        "label": label,
        "title": title,
        "description": description,
        "action_type": action_type,
        "generation_priority": _generation_priority(kind, action_type),
        "estimated_seedream_images": 0 if action_type == "bind_existing" else 1,
        "reuse_scope": "project_reference" if kind in PLANNABLE_REF_KINDS else "shot_only",
        "status": "recommended",
        "target_ref_field": REF_FIELDS.get(kind, ""),
        "prompt_seed": _prompt_seed(kind, prompt),
        "recommended_asset_ids": [item["asset_id"] for item in recommendations],
        "blocked_reason": _preflight_reason(kind, preflight),
    }


def _action_description(kind: str, subject: str) -> str:
    descriptions = {
        "character": f"补一张{subject}，固定脸型、发型、年龄感和主要服装轮廓。",
        "scene": f"补一张{subject}，固定空间布局、柜台/背景关系、灯光和复杂度。",
        "prop": f"补一张{subject}，固定外形、材质、尺寸和可见文字/标识。",
        "costume": f"补一张{subject}，固定服装、妆造、手套等可连续的造型要素。",
        "style": f"补一张{subject}，固定色彩、光线、镜头质感和品牌调性。",
    }
    return descriptions.get(kind, f"补一张{subject}。")


def _asset_subject(kind: str, prompt: str) -> str:
    compact = re.sub(r"\s+", "", prompt)
    if kind == "scene":
        if "金店" in compact or "柜台" in compact:
            return "金店柜台场景参考"
        return _first_hint(compact, SCENE_HINTS, "场景参考")
    if kind == "prop":
        if _contains_any(compact, ("黄金", "金饰", "戒指", "手镯", "项链")):
            return "黄金道具参考"
        return _first_hint(compact, PROP_HINTS, "道具参考")
    if kind == "character":
        if "店员" in compact:
            return "店员角色参考"
        if "顾客" in compact:
            return "顾客角色参考"
        return "角色参考"
    if kind == "costume":
        return _first_hint(compact, COSTUME_HINTS, "服化道参考")
    if kind == "style":
        if _contains_any(compact, ("黄金回收", "金店", "商业", "广告")):
            return "黄金回收商业片风格参考"
        return "风格参考"
    return KIND_LABELS.get(kind, kind)


def _prompt_seed(kind: str, prompt: str) -> str:
    compact_prompt = re.sub(r"\s+", " ", prompt).strip()
    base = compact_prompt[:140]
    controls = {
        "character": "单人正脸和半身，干净背景，身份特征清晰，可作为连续角色参考",
        "scene": "无人物主场景，空间布局清晰，灯光稳定，可作为场景参考",
        "prop": "单个道具特写，材质和形状清晰，干净背景，可作为道具参考",
        "costume": "服装妆造清晰，正面半身，颜色和配件可复用",
        "style": "色彩、光线、镜头质感统一，适合作为整片视觉风格参考",
    }
    return f"{base}。资产类型：{KIND_LABELS.get(kind, kind)}。{controls.get(kind, '')}".strip()


def _preflight_reason(kind: str, preflight: dict[str, Any]) -> str:
    for risk in preflight.get("risks") or []:
        if not isinstance(risk, dict):
            continue
        code = str(risk.get("code") or "")
        if kind in code:
            return str(risk.get("reason") or risk.get("title") or "")
    return ""


def _build_seedream_budget(action_items: list[dict[str, Any]], shots: list[dict[str, Any]]) -> dict[str, Any]:
    generate_reference_actions = [
        item for item in action_items
        if isinstance(item, dict) and item.get("action_type") == "generate_reference"
    ]
    bind_existing_count = sum(
        1 for item in action_items
        if isinstance(item, dict) and item.get("action_type") == "bind_existing"
    )
    unique_reference_groups = {_reference_group_key(item) for item in generate_reference_actions}
    pending_keyframes = sum(1 for shot in shots if str(shot.get("prompt") or "").strip() and not shot.get("selected_image"))
    selected_keyframes = sum(1 for shot in shots if bool(shot.get("selected_image")))
    estimated_without_reuse = len(generate_reference_actions) + pending_keyframes
    estimated_with_reuse = len(unique_reference_groups) + pending_keyframes
    avoided = max(0, estimated_without_reuse - estimated_with_reuse + bind_existing_count)
    reusable_action_count = bind_existing_count + len(unique_reference_groups)
    total_reference_needs = bind_existing_count + len(generate_reference_actions)
    reuse_ratio_percent = int(round(100 * reusable_action_count / max(total_reference_needs, 1))) if total_reference_needs else 100
    budget_level = _budget_level(estimated_with_reuse)
    priority_order = [
        item["id"]
        for item in sorted(
            action_items,
            key=lambda item: (
                _priority_rank(str(item.get("generation_priority") or "")),
                int(item.get("shot_index") or 0),
                str(item.get("kind") or ""),
            ),
        )
    ]
    recommendations = []
    if bind_existing_count:
        recommendations.append(f"优先绑定 {bind_existing_count} 个已有资产，避免重复出图。")
    if avoided:
        recommendations.append(f"通过复用/合并参考，预计少生成 {avoided} 张 Seedream 图片。")
    if budget_level == "over_budget":
        recommendations.append("图片预算偏高，先生成角色/场景/风格母版，再分批补关键帧。")
    elif pending_keyframes:
        recommendations.append("关键帧按分镜顺序分批生成，先跑前 3-5 个镜头验证一致性。")
    return {
        "action_count": len(action_items),
        "bind_existing_count": bind_existing_count,
        "generate_reference_action_count": len(generate_reference_actions),
        "unique_reference_generation_count": len(unique_reference_groups),
        "pending_keyframe_count": pending_keyframes,
        "selected_keyframe_count": selected_keyframes,
        "estimated_without_reuse": estimated_without_reuse,
        "estimated_seedream_images": estimated_with_reuse,
        "avoided_seedream_images": avoided,
        "reuse_ratio_percent": reuse_ratio_percent,
        "budget_level": budget_level,
        "priority_order": priority_order,
        "recommendations": recommendations,
    }


def _generation_priority(kind: str, action_type: str) -> str:
    if action_type == "bind_existing":
        return "reuse_first"
    if kind in {"character", "scene", "style"}:
        return "critical"
    if kind in {"prop", "costume"}:
        return "high"
    return "normal"


def _priority_rank(priority: str) -> int:
    return {
        "reuse_first": 0,
        "critical": 1,
        "high": 2,
        "normal": 3,
    }.get(priority, 9)


def _budget_level(estimated_images: int) -> str:
    if estimated_images >= 13:
        return "over_budget"
    if estimated_images >= 8:
        return "watch"
    return "ok"


def _reference_group_key(action: dict[str, Any]) -> str:
    kind = str(action.get("kind") or "").strip().lower()
    title = str(action.get("title") or "").strip().lower()
    prompt_seed = str(action.get("prompt_seed") or "").strip().lower()
    return f"{kind}:{title or prompt_seed[:80]}"


def _score(required: list[str], current: dict[str, list[str]], recommendations: dict[str, list[dict[str, Any]]]) -> int:
    if not required:
        return 100
    points = 0
    for kind in required:
        if current.get(kind):
            points += 100
        elif recommendations.get(kind):
            points += 55
    return int(round(points / len(required)))


def _risk_level(
    score: int,
    missing: list[str],
    action_items: list[dict[str, Any]],
    preflight: dict[str, Any],
) -> str:
    preflight_level = str(preflight.get("risk_level") or "")
    if preflight_level == "blocked":
        return "blocked"
    if missing and any(item.get("action_type") == "generate_reference" for item in action_items):
        return "blocked" if score < 55 else "warning"
    return "ready" if score >= 85 else "warning" if score >= 55 else "blocked"


def _suggestions(
    missing: list[str],
    recommendations: dict[str, list[dict[str, Any]]],
    action_items: list[dict[str, Any]],
) -> list[str]:
    if not missing:
        return ["视觉参考已基本齐备，可进入关键帧或视频生成。"]
    by_kind = {item["kind"]: item for item in action_items}
    result = []
    for kind in missing:
        label = KIND_LABELS.get(kind, kind)
        action = by_kind.get(kind, {})
        if recommendations.get(kind):
            result.append(f"缺少已绑定{label}，可先绑定推荐资产：{action.get('title', label)}。")
        else:
            result.append(f"缺少{label}资产，建议先{action.get('title', f'生成{label}参考')}。")
    return result


def _default_locked_traits(kind: str) -> list[str]:
    return {
        "character": ["face", "hair", "body_shape"],
        "scene": ["layout", "lighting", "time_of_day"],
        "prop": ["shape", "material"],
        "costume": ["costume", "makeup", "color"],
        "style": ["color", "lighting", "lens"],
        "shot_keyframe": ["composition", "subject", "scene"],
    }.get(kind, [])


def _normalize_kind_list(value: Any) -> list[str]:
    return [
        kind
        for kind in (normalize_asset_kind(item, fallback="") for item in _as_list(value))
        if kind in PLANNABLE_REF_KINDS
    ]


def _merge_kinds(*groups: list[str]) -> list[str]:
    seen = set()
    result = []
    for group in groups:
        for kind in group:
            if kind not in PLANNABLE_REF_KINDS or kind in seen:
                continue
            seen.add(kind)
            result.append(kind)
    return result


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _first_hint(text: str, hints: tuple[str, ...], fallback: str) -> str:
    for hint in hints:
        if hint in text:
            return f"{hint}参考"
    return fallback


def _token_overlap(left: str, right: str) -> int:
    if not left or not right:
        return 0
    left_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", left.lower()))
    right_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", right.lower()))
    if not left_tokens or not right_tokens:
        return 0
    return len(left_tokens & right_tokens)
