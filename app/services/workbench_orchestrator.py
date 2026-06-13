"""Workbench orchestrator — workflow coordination layer for node workbench v1.

This module provides the unified entry points for batch operations,
pre-flight validation, and payload assembly. It sits between the HTTP
routes and the actual generation services.

Node flow: Asset Pack → ref_resolver → orchestrator → batch execute
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..db import AsyncSessionLocal
from .ref_resolver import RefResolutionError, build_image_generation_payload, build_video_generation_payload, validate_refs


@dataclass
class ValidationResult:
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    blocked_shots: list[int] = field(default_factory=list)


def _run_async_sync(coro):
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


def _decode_shot_row(row: dict | None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    for key in (
        "character_refs_json",
        "scene_refs_json",
        "prop_refs_json",
        "costume_refs_json",
        "style_refs_json",
        "image_candidates_json",
        "video_variants_json",
        "continuity_json",
        "execution_plan_json",
    ):
        target_key = key.replace("_json", "")
        raw_value = data.pop(key, None)
        try:
            data[target_key] = json.loads(raw_value or ("{}" if target_key in {"continuity", "execution_plan"} else "[]"))
        except Exception:
            data[target_key] = {} if target_key in {"continuity", "execution_plan"} else []
    return data


async def _fetch_asset_row(asset_id: str) -> dict | None:
    query = text("SELECT * FROM assets WHERE asset_id = :asset_id LIMIT 1")
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(query, {"asset_id": asset_id})
            row = result.mappings().first()
            return dict(row) if row else None
    except SQLAlchemyError:
        return None


async def _fetch_shot_row(project_id: str, shot_index: int) -> dict | None:
    query = text(
        "SELECT * FROM shot_rows WHERE project_id = :project_id AND shot_index = :shot_index LIMIT 1"
    )
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(query, {"project_id": project_id, "shot_index": shot_index})
            row = result.mappings().first()
            return _decode_shot_row(dict(row)) if row else None
    except SQLAlchemyError:
        return None


async def _fetch_shot_rows(project_id: str) -> list[dict]:
    query = text("SELECT * FROM shot_rows WHERE project_id = :project_id ORDER BY shot_index")
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(query, {"project_id": project_id})
            return [_decode_shot_row(dict(row)) or {} for row in result.mappings().all()]
    except SQLAlchemyError:
        return []


def get_asset(asset_id: str) -> dict | None:
    return _run_async_sync(_fetch_asset_row(asset_id))


def get_shot_row(project_id: str, shot_index: int) -> dict | None:
    return _run_async_sync(_fetch_shot_row(project_id, shot_index))


def list_shot_rows(project_id: str) -> list[dict]:
    return _run_async_sync(_fetch_shot_rows(project_id))


def validate_asset_pack(asset_id: str) -> list[str]:
    """Validate that an asset pack has required structure.

    Checks:
    - Asset exists and is active
    - metadata_json contains pack=true
    - views dict is non-empty
    - primary view exists in views

    Returns list of error messages. Empty = valid.
    """
    asset = get_asset(asset_id)
    if not asset:
        return [f"asset {asset_id} not found"]
    if asset.get("status") != "active":
        return [f"asset {asset_id} status={asset.get('status')}"]

    raw_meta = asset.get("metadata_json") or "{}"
    try:
        meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
    except (json.JSONDecodeError, TypeError):
        return [f"asset {asset_id} metadata_json invalid"]

    if not meta.get("pack"):
        return []  # not a pack, single-image asset — valid by default

    views = meta.get("views")
    if not isinstance(views, dict) or not views:
        return [f"asset {asset_id} pack=true but views is empty"]

    primary = meta.get("primary", "front")
    if primary not in views:
        return [f"asset {asset_id} primary='{primary}' not found in views keys: {list(views.keys())}"]

    return []


def validate_batch_images(project_id: str, shot_indices: list[int] | None = None) -> ValidationResult:
    """Pre-flight validation for batch_generate_images.

    Checks:
    - At least one eligible row exists
    - All eligible rows have non-empty prompt
    - All refs point to valid, active assets
    """
    result = ValidationResult()
    all_rows = list_shot_rows(project_id)

    if shot_indices is not None:
        targets = [r for r in all_rows if r["shot_index"] in shot_indices and r["status"] == "ready"]
    else:
        targets = [r for r in all_rows if r.get("selected") and r["status"] == "ready"]

    if not targets:
        result.valid = False
        result.errors.append("没有满足条件的镜头（需要 selected=true 且 status=ready）")
        return result

    for row in targets:
        idx = row["shot_index"]

        if not (row.get("prompt") or "").strip():
            result.valid = False
            result.errors.append(f"第{idx}行缺少提示词")
            result.blocked_shots.append(idx)
            continue

        ref_errors = validate_refs(row)
        if ref_errors:
            result.valid = False
            for err in ref_errors:
                result.errors.append(f"第{idx}行: {err}")
            result.blocked_shots.append(idx)
            continue

        for ref_field in ("character_refs", "scene_refs", "prop_refs", "costume_refs", "style_refs"):
            for aid in (row.get(ref_field) or []):
                pack_errors = validate_asset_pack(aid)
                if pack_errors:
                    result.valid = False
                    for err in pack_errors:
                        result.errors.append(f"第{idx}行 {ref_field}: {err}")
                    if idx not in result.blocked_shots:
                        result.blocked_shots.append(idx)

    return result


def validate_batch_videos(project_id: str, shot_indices: list[int] | None = None) -> ValidationResult:
    """Pre-flight validation for batch_generate_videos.

    Checks:
    - At least one eligible row exists
    - All eligible rows have selected_image
    - Duration in valid range [2.0, 10.0]
    - All character_refs point to valid assets
    """
    result = ValidationResult()
    all_rows = list_shot_rows(project_id)

    if shot_indices is not None:
        targets = [
            r for r in all_rows
            if r["shot_index"] in shot_indices
            and r["status"] == "image_done"
            and r.get("selected_image")
        ]
    else:
        targets = [
            r for r in all_rows
            if r.get("selected")
            and r["status"] == "image_done"
            and r.get("selected_image")
        ]

    if not targets:
        result.valid = False
        result.errors.append("没有满足条件的镜头（需要 status=image_done 且已选择参考图）")
        return result

    for row in targets:
        idx = row["shot_index"]

        if not row.get("selected_image"):
            result.valid = False
            result.errors.append(f"第{idx}行未选择参考图")
            result.blocked_shots.append(idx)
            continue

        duration = float(row.get("duration") or 5.0)
        if duration < 2.0 or duration > 10.0:
            result.valid = False
            result.errors.append(f"第{idx}行时长 {duration}s 超出范围 [2.0, 10.0]")
            result.blocked_shots.append(idx)
            continue

        ref_errors = validate_refs(row)
        if ref_errors:
            result.valid = False
            for err in ref_errors:
                result.errors.append(f"第{idx}行: {err}")
            result.blocked_shots.append(idx)

    return result


def prepare_image_payloads(project_id: str, shot_indices: list[int] | None = None) -> list[dict]:
    """Prepare generation payloads for all eligible shots.

    Returns list of dicts, each containing:
        - shot_index
        - payload (for seedream)
        - row (original shot_row)
    """
    all_rows = list_shot_rows(project_id)

    if shot_indices is not None:
        targets = [r for r in all_rows if r["shot_index"] in shot_indices and r["status"] == "ready"]
    else:
        targets = [r for r in all_rows if r.get("selected") and r["status"] == "ready"]

    results = []
    for row in targets:
        try:
            payload = build_image_generation_payload(row, strict=False)
        except RefResolutionError:
            payload = {"prompt": row.get("prompt", ""), "subject_reference": [], "scene_reference": [], "style_reference": []}

        results.append({
            "shot_index": row["shot_index"],
            "payload": payload,
            "row": row,
        })

    return results


def prepare_video_payloads(project_id: str, shot_indices: list[int] | None = None) -> list[dict]:
    """Prepare generation payloads for all eligible shots.

    Returns list of dicts, each containing:
        - shot_index
        - payload (for seedance)
        - row (original shot_row)
    """
    all_rows = list_shot_rows(project_id)

    if shot_indices is not None:
        targets = [
            r for r in all_rows
            if r["shot_index"] in shot_indices
            and r["status"] == "image_done"
            and r.get("selected_image")
        ]
    else:
        targets = [
            r for r in all_rows
            if r.get("selected")
            and r["status"] == "image_done"
            and r.get("selected_image")
        ]

    results = []
    for row in targets:
        try:
            payload = build_video_generation_payload(row, strict=False)
        except RefResolutionError:
            payload = {"image": row.get("selected_image", ""), "prompt": row.get("prompt", ""), "duration": 5, "subject_reference": []}

        results.append({
            "shot_index": row["shot_index"],
            "payload": payload,
            "row": row,
        })

    return results
