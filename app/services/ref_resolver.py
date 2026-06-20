"""Structured reference asset resolution for shot rows and batch payloads.

Key improvements over the original:

1. **Batch asset queries** — ``_normalize_assets_map()`` now collects all
   unique asset IDs first, then fetches them in a single DB round-trip via
   ``batch_get_assets()``, instead of N individual ``_get_asset()`` calls.
2. **No ``asyncio.run()`` in sync code** — uses ``app.core.async_bridge.run_async``
   which detects a running event loop and schedules the coroutine correctly.
3. **No per-call ``ThreadPoolExecutor``** — the bridge owns a single shared pool.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..core.async_bridge import run_async
from ..db import AsyncSessionLocal
from .visual_quality_rules import apply_video_motion_controls, apply_visual_quality_controls

STORAGE = Path(__file__).resolve().parents[2] / "storage" / "projects"

_REF_LIMITS: dict[str, int] = {
    "character_refs": 3,
    "scene_refs": 2,
    "prop_refs": 3,
    "costume_refs": 2,
    "style_refs": 1,
}

_ROLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("character_refs", "character"),
    ("scene_refs", "scene"),
    ("prop_refs", "prop"),
    ("costume_refs", "costume"),
    ("style_refs", "style"),
)

_DEFAULT_VIEW_KEYWORDS: dict[str, tuple[str, ...]] = {
    "front": ("front", "正面", "正脸", "正视", "正对镜头"),
    "primary": ("primary", "主视图", "默认视图"),
    "side": ("side", "profile", "侧脸", "侧面", "侧视"),
    "back": ("back", "rear", "behind", "背影", "背面", "背后"),
    "close_up": ("close up", "close-up", "closeup", "近景", "近距", "特写"),
    "medium": ("medium shot", "中景", "半身"),
    "wide": ("wide", "wide shot", "全景", "远景"),
    "expression_smile": ("smile", "smiling", "微笑", "笑容"),
}


class RefResolutionError(RuntimeError):
    """Raised when refs cannot be resolved under strict mode."""


# ── Batch DB access ──────────────────────────────────────────────────────────

async def _fetch_assets_batch(asset_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch multiple assets in a single round-trip."""
    if not asset_ids:
        return []
    query = text(
        "SELECT * FROM assets WHERE asset_id = ANY(:asset_ids)"
    )
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(query, {"asset_ids": asset_ids})
            rows = result.mappings().fetchall()
            return [dict(row) for row in rows]
    except SQLAlchemyError:
        return []


def _batch_get_assets_sync(asset_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Synchronous wrapper — fetches all *asset_ids* in one DB call.

    Uses ``app.core.async_bridge.run_async`` so it works correctly whether
    called from sync code or from inside a running event loop (the original
    ``asyncio.run()`` approach crashes in the latter case).
    """
    if not asset_ids:
        return {}
    rows = run_async(_fetch_assets_batch(asset_ids))
    return {row["asset_id"]: _normalize_asset_row(row) for row in rows}


# ── Public API ───────────────────────────────────────────────────────────────


def sanitize_ref_list(raw_refs: Any, *, field_name: str) -> list[str]:
    """Deduplicate and limit reference IDs for *field_name*."""
    refs: list[str] = []
    seen: set[str] = set()
    for item in raw_refs or []:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        refs.append(value)
    limit = _REF_LIMITS.get(field_name, 3)
    return refs[:limit]


def resolve_refs(shot_row: dict, assets_by_id: dict[str, dict] | None = None) -> dict:
    project_id = str(shot_row.get("project_id") or "").strip()
    return resolve_refs_pack(project_id, shot_row, assets_by_id=assets_by_id)


def resolve_refs_pack(
    project_id: str, row: dict, *, assets_by_id: dict[str, dict] | None = None
) -> dict:
    prompt = str(row.get("prompt") or "")
    normalized_assets = _normalize_assets_map(row, assets_by_id)
    refs_payload: dict[str, dict[str, Any]] = {}
    has_missing = False
    anchor_locks = _resolve_anchor_locks(row)

    for field_name, role in _ROLE_FIELDS:
        asset_ids = sanitize_ref_list(row.get(field_name, []), field_name=field_name)
        resolved_assets: list[dict[str, Any]] = []
        resolution_items: list[dict[str, Any]] = []
        missing_asset_ids: list[str] = []
        missing_details: list[dict[str, Any]] = []
        selected_views: list[dict[str, Any]] = []

        for asset_id in asset_ids:
            asset = normalized_assets.get(asset_id)
            if not asset or asset.get("status") != "active":
                missing_asset_ids.append(asset_id)
                missing_details.append({"asset_id": asset_id, "reason": "asset_missing_or_inactive"})
                continue

            resolution = _resolve_asset_reference(asset, prompt=prompt, role=role)
            if not resolution.get("selected_url"):
                missing_asset_ids.append(asset_id)
                missing_details.append({
                    "asset_id": asset_id,
                    "reason": resolution.get("error_reason") or "asset_url_unavailable",
                })
                continue

            resolution_items.append(resolution)
            resolved_asset = {
                "asset_id": asset["asset_id"],
                "asset_type": asset.get("asset_type", "image"),
                "file_path": resolution.get("selected_path") or asset.get("file_path"),
                "file_url": resolution["selected_url"],
                "metadata": asset.get("metadata", {}),
                "pack_enabled": resolution.get("pack_enabled", False),
                "pack_valid": resolution.get("pack_valid", False),
                "selected_view": resolution.get("selected_view"),
                "fallback_used": resolution.get("fallback_used", False),
                "fallback_reason": resolution.get("fallback_reason") or "",
                "match_reason": resolution.get("match_reason") or "",
                "available_views": resolution.get("available_views", []),
            }
            resolved_assets.append(resolved_asset)
            selected_views.append({
                "asset_id": asset["asset_id"],
                "selected_view": resolution.get("selected_view"),
                "selected_url": resolution["selected_url"],
                "fallback_used": resolution.get("fallback_used", False),
                "fallback_reason": resolution.get("fallback_reason") or "",
                "match_reason": resolution.get("match_reason") or "",
            })

        if missing_asset_ids:
            has_missing = True

        refs_payload[role] = {
            "field": field_name,
            "asset_ids": asset_ids,
            "resolved_assets": resolved_assets,
            "resolved_urls": [a["file_url"] for a in resolved_assets],
            "missing_asset_ids": missing_asset_ids,
            "missing_details": missing_details,
            "resolution_items": resolution_items,
            "selected_views": selected_views,
            "fallback_used": any(item.get("fallback_used") for item in resolution_items),
            "fallback_count": sum(1 for item in resolution_items if item.get("fallback_used")),
            "pack_asset_count": sum(1 for item in resolution_items if item.get("pack_enabled")),
        }

    anchor_priority_roles = _build_anchor_priority_roles(anchor_locks)
    combined_asset_ids, combined_urls = _flatten_priority_refs(refs_payload, anchor_priority_roles)
    anchor_warnings = _build_anchor_warnings(refs_payload, anchor_locks)

    return {
        "project_id": project_id or row.get("project_id"),
        "shot_index": row.get("shot_index"),
        "character": refs_payload["character"],
        "scene": refs_payload["scene"],
        "prop": refs_payload["prop"],
        "costume": refs_payload["costume"],
        "style": refs_payload["style"],
        "anchor_locks": anchor_locks,
        "anchor_priority_roles": anchor_priority_roles,
        "anchor_warnings": anchor_warnings,
        "all_asset_ids": combined_asset_ids,
        "all_urls": combined_urls,
        "has_missing": has_missing,
    }


def validate_refs(shot_row: dict, assets_by_id: dict[str, dict] | None = None) -> list[str]:
    refs_payload = resolve_refs(shot_row, assets_by_id=assets_by_id)
    errors: list[str] = []
    for role in ("character", "scene", "prop", "costume", "style"):
        missing_details = refs_payload.get(role, {}).get("missing_details", [])
        for detail in missing_details:
            asset_id = detail.get("asset_id") or ""
            reason = detail.get("reason") or "asset_unavailable"
            errors.append(f"{role} ref {asset_id} failed: {reason}")
    return errors


def build_image_generation_payload(
    shot_row: dict,
    *,
    strict: bool = True,
    assets_by_id: dict[str, dict] | None = None,
) -> dict:
    refs_payload = resolve_refs(shot_row, assets_by_id=assets_by_id)
    errors = validate_refs(shot_row, assets_by_id=assets_by_id)
    if strict and errors:
        raise RefResolutionError("; ".join(errors))
    prompt = apply_visual_quality_controls(str(shot_row.get("prompt") or ""), refs_pack=refs_payload)
    payload = {
        "prompt": build_image_prompt(prompt, refs_payload),
        "subject_reference": refs_payload["character"]["resolved_urls"],
        "scene_reference": refs_payload["scene"]["resolved_urls"],
        "prop_reference": refs_payload["prop"]["resolved_urls"],
        "costume_reference": refs_payload["costume"]["resolved_urls"],
        "style_reference": refs_payload["style"]["resolved_urls"],
        "refs": refs_payload,
    }
    _copy_director_protocol(shot_row, payload)
    return payload


def build_video_generation_payload(
    shot_row: dict,
    *,
    strict: bool = True,
    assets_by_id: dict[str, dict] | None = None,
) -> dict:
    refs_payload = resolve_refs(shot_row, assets_by_id=assets_by_id)
    errors = validate_refs(shot_row, assets_by_id=assets_by_id)
    if strict and errors:
        raise RefResolutionError("; ".join(errors))
    selected_image = str(shot_row.get("selected_image") or "")
    prompt = apply_visual_quality_controls(str(shot_row.get("prompt") or ""), refs_pack=refs_payload)
    prompt = apply_video_motion_controls(prompt)
    payload = {
        "image": selected_image,
        "prompt": prompt,
        "duration": int(round(float(shot_row.get("duration") or 5.0))),
        "subject_reference": extract_video_ref_images(refs_payload, exclude_url=selected_image),
        "refs": refs_payload,
    }
    _copy_director_protocol(shot_row, payload)
    return payload


def build_image_prompt(prompt: str, pack: dict) -> str:
    blocks: list[str] = []
    role_labels = {
        "character": "subject_reference_urls",
        "scene": "scene_reference_urls",
        "prop": "prop_reference_urls",
        "costume": "costume_reference_urls",
        "style": "style_reference_urls",
    }
    ordered_roles = pack.get("anchor_priority_roles") or ["character", "scene", "prop", "costume", "style"]
    for role in ordered_roles:
        resolved_urls = pack.get(role, {}).get("resolved_urls") or []
        if resolved_urls:
            blocks.append(role_labels[role] + "=" + ", ".join(resolved_urls))
    anchor_locks = pack.get("anchor_locks") or {}
    continuity_rules: list[str] = []
    if anchor_locks.get("lock_character"):
        continuity_rules.append("keep_character_identity_consistent")
    if anchor_locks.get("lock_scene"):
        continuity_rules.append("keep_scene_layout_consistent")
    if anchor_locks.get("lock_costume"):
        continuity_rules.append("keep_costume_consistent")
    if anchor_locks.get("lock_prop"):
        continuity_rules.append("keep_key_props_consistent")
    if continuity_rules:
        blocks.append("continuity_rules=" + ", ".join(continuity_rules))
    if not blocks:
        return prompt
    return f"{prompt}\n\n[reference_assets]\n" + "\n".join(blocks)


def extract_video_ref_images(pack: dict, *, exclude_url: str | None = None) -> list[str]:
    seen: set[str] = set()
    if exclude_url:
        seen.add(exclude_url)
    result: list[str] = []
    for url in pack.get("all_urls", []):
        if url and url not in seen:
            seen.add(url)
            result.append(url)
    return result


def _copy_director_protocol(source: dict, payload: dict) -> None:
    protocol = source.get("director_input_protocol")
    if isinstance(protocol, dict):
        payload["director_input_protocol"] = protocol


def refs_evidence(pack: dict) -> dict:
    selected_views = {
        role: [
            {
                "asset_id": item.get("asset_id"),
                "selected_view": item.get("selected_view"),
                "fallback_used": item.get("fallback_used", False),
                "fallback_reason": item.get("fallback_reason") or "",
            }
            for item in pack.get(role, {}).get("selected_views", [])
        ]
        for role in ("character", "scene", "prop", "costume", "style")
    }
    return {
        "project_id": pack.get("project_id"),
        "shot_index": pack.get("shot_index"),
        "character_ref_count": len(pack.get("character", {}).get("resolved_assets", [])),
        "scene_ref_count": len(pack.get("scene", {}).get("resolved_assets", [])),
        "prop_ref_count": len(pack.get("prop", {}).get("resolved_assets", [])),
        "costume_ref_count": len(pack.get("costume", {}).get("resolved_assets", [])),
        "style_ref_count": len(pack.get("style", {}).get("resolved_assets", [])),
        "anchor_locks": pack.get("anchor_locks", {}),
        "anchor_priority_roles": pack.get("anchor_priority_roles", []),
        "anchor_warnings": pack.get("anchor_warnings", []),
        "resolved_asset_ids": pack.get("all_asset_ids", []),
        "resolved_urls": pack.get("all_urls", []),
        "selected_views": selected_views,
        "fallback_count": sum(
            int(pack.get(role, {}).get("fallback_count", 0))
            for role in ("character", "scene", "prop", "costume", "style")
        ),
        "has_missing": pack.get("has_missing", False),
    }


def refs_event_fields(pack: dict) -> dict:
    data = refs_evidence(pack)
    data.pop("project_id", None)
    data.pop("shot_index", None)
    return data


# ── Internal helpers ─────────────────────────────────────────────────────────


def _normalize_assets_map(row: dict, assets_by_id: dict[str, dict] | None) -> dict[str, dict]:
    """Normalize asset map — batch-fetches from DB if ``assets_by_id`` is None.

    Old behaviour: called ``_get_asset()`` in a loop, creating N individual
    DB round-trips, each spawning its own ``ThreadPoolExecutor`` + ``asyncio.run()``.

    New behaviour: collects all unique asset IDs, fetches them in **one** DB
    round-trip via ``_batch_get_assets_sync()``.
    """
    if assets_by_id:
        return {asset_id: _normalize_asset_row(asset) for asset_id, asset in assets_by_id.items()}

    # Collect all unique asset IDs from every role field
    all_ids: list[str] = []
    seen_ids: set[str] = set()
    for field_name, _role in _ROLE_FIELDS:
        for asset_id in sanitize_ref_list(row.get(field_name, []), field_name=field_name):
            if asset_id not in seen_ids:
                seen_ids.add(asset_id)
                all_ids.append(asset_id)

    if not all_ids:
        return {}

    return _batch_get_assets_sync(all_ids)


def _resolve_anchor_locks(row: dict) -> dict[str, bool]:
    execution_plan = row.get("execution_plan") if isinstance(row.get("execution_plan"), dict) else {}
    continuity = row.get("continuity") if isinstance(row.get("continuity"), dict) else {}
    anchors = execution_plan.get("anchors") if isinstance(execution_plan.get("anchors"), dict) else {}
    return {
        "lock_character": _coerce_bool(
            row.get("lock_character"),
            execution_plan.get("lock_character"),
            continuity.get("lock_character"),
            anchors.get("lock_character"),
        ),
        "lock_scene": _coerce_bool(
            row.get("lock_scene"),
            execution_plan.get("lock_scene"),
            continuity.get("lock_scene"),
            anchors.get("lock_scene"),
        ),
        "lock_costume": _coerce_bool(
            row.get("lock_costume"),
            execution_plan.get("lock_costume"),
            continuity.get("lock_costume"),
            anchors.get("lock_costume"),
        ),
        "lock_prop": _coerce_bool(
            row.get("lock_prop"),
            execution_plan.get("lock_prop"),
            continuity.get("lock_prop"),
            anchors.get("lock_prop"),
        ),
    }


def _build_anchor_priority_roles(anchor_locks: dict[str, bool]) -> list[str]:
    roles = ["character", "scene", "prop", "costume", "style"]
    prioritized: list[str] = []
    if anchor_locks.get("lock_character"):
        prioritized.append("character")
    if anchor_locks.get("lock_scene"):
        prioritized.append("scene")
    if anchor_locks.get("lock_prop"):
        prioritized.append("prop")
    if anchor_locks.get("lock_costume"):
        prioritized.append("costume")
    for role in roles:
        if role not in prioritized:
            prioritized.append(role)
    return prioritized


def _flatten_priority_refs(
    refs_payload: dict[str, dict[str, Any]], priority_roles: list[str]
) -> tuple[list[str], list[str]]:
    combined_asset_ids: list[str] = []
    combined_urls: list[str] = []
    for role in priority_roles:
        role_payload = refs_payload.get(role, {})
        for asset in role_payload.get("resolved_assets", []):
            asset_id = str(asset.get("asset_id") or "").strip()
            file_url = str(asset.get("file_url") or "").strip()
            if asset_id and asset_id not in combined_asset_ids:
                combined_asset_ids.append(asset_id)
            if file_url and file_url not in combined_urls:
                combined_urls.append(file_url)
    return combined_asset_ids, combined_urls


def _build_anchor_warnings(
    refs_payload: dict[str, dict[str, Any]], anchor_locks: dict[str, bool]
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for lock_key, role in (
        ("lock_character", "character"),
        ("lock_scene", "scene"),
        ("lock_costume", "costume"),
        ("lock_prop", "prop"),
    ):
        if not anchor_locks.get(lock_key):
            continue
        role_payload = refs_payload.get(role, {})
        asset_ids = role_payload.get("asset_ids", []) or []
        resolved_assets = role_payload.get("resolved_assets", []) or []
        if resolved_assets:
            continue
        warning_code = "LOCKED_ROLE_REFS_MISSING" if not asset_ids else "LOCKED_ROLE_REFS_UNRESOLVED"
        warnings.append({
            "lock_key": lock_key,
            "role": role,
            "warning_code": warning_code,
            "message": f"{role} refs unavailable while {lock_key}=true",
            "asset_ids": asset_ids,
            "missing_asset_ids": role_payload.get("missing_asset_ids", []),
        })
    return warnings


def _coerce_bool(*values: Any) -> bool:
    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return False


def _normalize_asset_row(asset: dict) -> dict:
    row = dict(asset or {})
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        metadata = _parse_metadata(row.get("metadata_json"))
    row["metadata"] = metadata
    if row.get("file_path") and not row.get("file_url"):
        row["file_url"] = _to_asset_url(row.get("file_path")) or row.get("file_url") or ""
    return row


def _parse_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _resolve_asset_reference(asset: dict, *, prompt: str, role: str) -> dict[str, Any]:
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata"), dict) else {}
    pack_enabled = bool(metadata.get("pack"))
    primary = _normalize_view_name(metadata.get("primary") or "front") or "front"
    default_view = _normalize_view_name(metadata.get("default_view") or primary) or primary
    views_raw = metadata.get("views")
    normalized_views = _normalize_views(views_raw)
    available_views = [name for name, item in normalized_views.items() if item.get("url")]

    if pack_enabled and available_views:
        matched_view, matched_keywords = _match_view(prompt, normalized_views)
        selected_view = matched_view or _choose_fallback_view(
            normalized_views,
            default_view=default_view,
            primary=primary,
        )
        selected_entry = normalized_views.get(selected_view or "", {})
        selected_url = selected_entry.get("url") or ""
        fallback_used = not bool(matched_view)
        fallback_reason = ""
        match_reason = "keyword_match" if matched_view else ""
        if not matched_view:
            fallback_reason = _fallback_reason(
                selected_view,
                default_view=default_view,
                primary=primary,
                available_views=available_views,
            )
            match_reason = fallback_reason
        if selected_url:
            return {
                "asset_id": asset.get("asset_id"),
                "asset_type": asset.get("asset_type", role),
                "pack_enabled": True,
                "pack_valid": True,
                "available_views": available_views,
                "selected_view": selected_view,
                "selected_url": selected_url,
                "selected_path": selected_entry.get("path") or "",
                "primary": primary,
                "default_view": default_view,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "match_reason": match_reason,
                "matched_keywords": matched_keywords,
                "metadata": metadata,
            }

    asset_url = _resolve_direct_asset_url(asset)
    if asset_url:
        return {
            "asset_id": asset.get("asset_id"),
            "asset_type": asset.get("asset_type", role),
            "pack_enabled": pack_enabled,
            "pack_valid": bool(available_views),
            "available_views": available_views,
            "selected_view": None,
            "selected_url": asset_url,
            "selected_path": str(asset.get("file_path") or ""),
            "primary": primary,
            "default_view": default_view,
            "fallback_used": pack_enabled,
            "fallback_reason": "asset_file" if pack_enabled else "",
            "match_reason": "asset_file",
            "matched_keywords": [],
            "metadata": metadata,
        }

    return {
        "asset_id": asset.get("asset_id"),
        "asset_type": asset.get("asset_type", role),
        "pack_enabled": pack_enabled,
        "pack_valid": bool(available_views),
        "available_views": available_views,
        "selected_view": None,
        "selected_url": "",
        "selected_path": "",
        "primary": primary,
        "default_view": default_view,
        "fallback_used": False,
        "fallback_reason": "",
        "match_reason": "",
        "matched_keywords": [],
        "metadata": metadata,
        "error_reason": "asset_url_unavailable",
    }


def _normalize_views(raw_views: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_views, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for view_name, raw_entry in raw_views.items():
        normalized_name = _normalize_view_name(view_name)
        if not normalized_name:
            continue
        entry = _normalize_view_entry(raw_entry)
        if entry.get("url"):
            normalized[normalized_name] = entry
    return normalized


def _normalize_view_entry(raw_entry: Any) -> dict[str, Any]:
    if isinstance(raw_entry, str):
        return {
            "url": _resolve_url_or_path(raw_entry),
            "path": _normalize_local_path(raw_entry),
            "keywords": [],
            "tags": [],
        }
    if not isinstance(raw_entry, dict):
        return {"url": "", "path": "", "keywords": [], "tags": []}

    url_value = str(raw_entry.get("url") or raw_entry.get("file_url") or "").strip()
    path_value = str(raw_entry.get("path") or raw_entry.get("file_path") or "").strip()
    resolved_url = _resolve_url_or_path(url_value or path_value)
    return {
        "url": resolved_url,
        "path": _normalize_local_path(path_value or url_value),
        "keywords": _normalize_string_list(raw_entry.get("keywords")),
        "tags": _normalize_string_list(raw_entry.get("tags")),
    }


def _normalize_string_list(raw_value: Any) -> list[str]:
    if isinstance(raw_value, str):
        values = [raw_value]
    elif isinstance(raw_value, (list, tuple, set)):
        values = list(raw_value)
    else:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item or "").strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _match_view(prompt: str, views: dict[str, dict[str, Any]]) -> tuple[str | None, list[str]]:
    prompt_text = (prompt or "").strip().lower()
    if not prompt_text:
        return None, []

    best_view: str | None = None
    best_keywords: list[str] = []
    best_score = 0
    for view_name, entry in views.items():
        keywords = _keywords_for_view(view_name, entry)
        matched = [keyword for keyword in keywords if keyword and keyword in prompt_text]
        score = len(matched)
        if view_name in prompt_text:
            score += 2
            matched.append(view_name)
        if score > best_score:
            best_view = view_name
            best_keywords = matched
            best_score = score
    return best_view, best_keywords


def _keywords_for_view(view_name: str, entry: dict[str, Any]) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for source in (
        entry.get("keywords", []),
        entry.get("tags", []),
        _DEFAULT_VIEW_KEYWORDS.get(view_name, ()),
        _split_view_tokens(view_name),
    ):
        for item in source:
            value = str(item or "").strip().lower()
            if not value or value in seen:
                continue
            seen.add(value)
            keywords.append(value)
    return keywords


def _split_view_tokens(view_name: str) -> list[str]:
    parts = [part for part in re.split(r"[^a-z0-9一-鿿]+", view_name.lower()) if part]
    return parts


def _choose_fallback_view(
    views: dict[str, dict[str, Any]],
    *,
    default_view: str,
    primary: str,
) -> str | None:
    for candidate in (default_view, primary, "front"):
        if candidate in views and views[candidate].get("url"):
            return candidate
    for view_name, entry in views.items():
        if entry.get("url"):
            return view_name
    return None


def _fallback_reason(
    selected_view: str | None,
    *,
    default_view: str,
    primary: str,
    available_views: list[str],
) -> str:
    if selected_view == default_view:
        return "default_view"
    if selected_view == primary:
        return "primary"
    if selected_view == "front":
        return "front"
    if selected_view and selected_view in available_views:
        return "first_available"
    return "asset_file"


def _resolve_direct_asset_url(asset: dict) -> str:
    for candidate in (asset.get("file_url"), asset.get("file_path")):
        resolved = _resolve_url_or_path(candidate)
        if resolved:
            return resolved
    return ""


def _resolve_url_or_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://", "data:")):
        return text
    if text.startswith("/assets/"):
        local_path = STORAGE / text[len("/assets/"):]
        return text if local_path.exists() else ""
    local_path = Path(text)
    if local_path.exists() and _path_is_within(STORAGE, local_path):
        return _to_asset_url(local_path) or ""
    return ""


def _normalize_local_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.startswith(("http://", "https://", "data:", "/assets/")):
        return ""
    local_path = Path(text)
    if local_path.exists() and _path_is_within(STORAGE, local_path):
        return str(local_path.resolve())
    return ""


def _to_asset_url(file_path: str | Path) -> str | None:
    try:
        relative = Path(file_path).resolve().relative_to(STORAGE.resolve())
    except Exception:
        return None
    return f"/assets/{relative.as_posix()}"


def _path_is_within(base_dir: str | Path, candidate: str | Path) -> bool:
    try:
        Path(candidate).resolve().relative_to(Path(base_dir).resolve())
        return True
    except Exception:
        return False


def _normalize_view_name(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
