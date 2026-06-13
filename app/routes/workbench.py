import json
import mimetypes
import uuid
from io import BytesIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.config import get_settings
from app.db import get_db
from app.middleware.auth import get_current_user
from app.middleware.credits import reserve_credits
from app.middleware.rate_limit import check_concurrent_limit, check_rate_limit
from app.services.final_edit import build_default_edit_plan, merge_plan_with_shots, normalize_edit_plan
from app.services.agent_runtime import (
    create_agent_run,
    emit_brain_snapshot_steps,
    ensure_run_budget,
    list_project_agent_events,
    list_project_agent_runs,
    publish_agent_event,
    record_agent_artifact,
    update_agent_run,
)
from app.services.agent_run_state_machine import evaluate_action_gate, recommend_next_action
from app.services.cost_guard import assert_cost_guard
from app.services.credits import credit_service
from app.services.director_preflight import analyze_shot_risk
from app.services.media_proxy import validate_public_media_url
from app.services.project_brain import build_project_brain
from app.services.project_continue import continue_project_from_brain
from app.services.project_workspace import init_project_workspace, read_project_workspace, write_project_workspace_file
from app.services.production_text_quality import analyze_production_text_effectiveness
from app.services.provider_prompt_adapter import adapt_provider_payload
from app.services.ref_resolver import STORAGE
from app.services.run_coordination import DecisionTickResult, evaluate_decision_tick, load_run_facts_from_snapshot
from app.services.run_dispatch_gateway import DispatchGatewayContext, dispatch_authoritative_packet
from app.services.showrunner_judgment import (
    ShowrunnerDecision,
    build_goal_card,
    judge_generation_preflight,
)
from app.services.shot_revision import (
    REVISION_SOURCE_DIRECTOR_PREFLIGHT,
    append_prompt_revision,
    build_prompt_revision,
    latest_prompt_revision,
    list_prompt_revisions,
    mark_prompt_revision_rolled_back,
    revision_public_payload,
)
from app.services.storage import storage_service
from app.services.requirement_pipeline import build_requirement_pipeline
from app.services.visual_planner import (
    REF_JSON_FIELDS,
    build_planned_reference_metadata,
    build_visual_plan,
    default_lineage_metadata,
)
from app.services.video_production_runner import VideoProductionRunner

router = APIRouter(prefix="/projects", tags=["workbench"])

MAX_IMPORTED_ASSET_BYTES = 200 * 1024 * 1024
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".webm"}
BRAIN_KEYFRAME_BATCH_MAX = 4
BRAIN_VIDEO_BATCH_MAX = 4


def _estimate_continue_credits(action: str, rows: list[dict[str, Any]], image_unit: int, video_unit: int) -> int:
    if action == "generate_keyframes":
        targets = [
            row for row in rows
            if row.get("prompt")
            and not row.get("selected_image")
            and str(row.get("status") or "") not in {"generating_image", "generating_video", "video_done"}
        ]
        return max(0, min(len(targets), BRAIN_KEYFRAME_BATCH_MAX) * max(0, int(image_unit)))
    if action == "generate_videos":
        targets = [
            row for row in rows
            if row.get("prompt")
            and row.get("selected_image")
            and not row.get("selected_video")
            and str(row.get("status") or "") not in {"generating_video", "video_done", "done", "final_done", "exported"}
        ]
        return max(0, min(len(targets), BRAIN_VIDEO_BATCH_MAX) * max(0, int(video_unit)))
    return 0


def _parse_json_object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        try:
            parsed = json.loads(text_value)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc
        if parsed is None:
            return None
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="JSON payload must be an object")
        return parsed
    raise HTTPException(status_code=400, detail="JSON payload type is not supported")


def _normalize_asset_metadata(body: dict[str, Any]) -> dict[str, Any] | None:
    # Backward/forward compatibility: allow either metadata or metadata_json.
    return _parse_json_object(body.get("metadata_json", body.get("metadata")))


def _guess_extension(filename: str | None, content_type: str | None) -> str:
    name_suffix = Path(filename or "").suffix.lower()
    if name_suffix:
        return name_suffix
    guessed = mimetypes.guess_extension(content_type or "")
    return guessed or ""


def _build_local_asset_paths(project_id: str, ext: str) -> tuple[Path, str]:
    base_dir = (STORAGE / project_id / "assets").resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{uuid.uuid4().hex}{ext}"
    abs_path = (base_dir / file_name).resolve()
    relative = abs_path.relative_to(STORAGE.resolve()).as_posix()
    return abs_path, f"/assets/{relative}"


def _validate_audio_asset(filename: str | None, content_type: str | None) -> None:
    ext = Path(filename or "").suffix.lower()
    content = (content_type or "").lower()
    if content.startswith("audio/"):
        return
    if ext in AUDIO_EXTENSIONS:
        return
    raise HTTPException(status_code=400, detail="Only audio files are supported for BGM assets")


def _normalize_asset_row(row: Any) -> dict[str, Any]:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    filename = str(metadata.get("filename") or "")
    file_url = row.file_url
    if not file_url:
        views = metadata.get("views") if isinstance(metadata, dict) else None
        if isinstance(views, dict):
            primary = str(metadata.get("primary") or "")
            primary_view = views.get(primary) if primary else None
            if isinstance(primary_view, str):
                file_url = primary_view
            elif isinstance(primary_view, dict):
                file_url = primary_view.get("url") or primary_view.get("file_url")
            if not file_url:
                for item in views.values():
                    if isinstance(item, str) and item:
                        file_url = item
                        break
                    if isinstance(item, dict) and (item.get("url") or item.get("file_url")):
                        file_url = item.get("url") or item.get("file_url")
                        break
    return {
        "id": row.asset_id,
        "asset_id": row.asset_id,
        "asset_type": row.asset_type,
        "file_path": row.file_path,
        "file_url": file_url,
        "filename": filename or None,
        "metadata": metadata,
        "metadata_json": row.metadata_json,
        "status": getattr(row, "status", "active"),
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at),
    }


def _normalize_shot_row_row(row: Any, *, project_id: str | None = None) -> dict[str, Any]:
    character_refs = row.character_refs_json or []
    scene_refs = row.scene_refs_json or []
    prop_refs = getattr(row, "prop_refs_json", None) or []
    costume_refs = getattr(row, "costume_refs_json", None) or []
    style_refs = row.style_refs_json or []
    image_candidates = row.image_candidates_json or []
    video_variants = row.video_variants_json or []
    normalized = {
        "shot_index": row.shot_index,
        "prompt": row.prompt,
        "duration": row.duration,
        "status": row.status,
        "selected": row.selected,
        # Canonical fields used by backend tasks:
        "character_refs_json": character_refs,
        "scene_refs_json": scene_refs,
        "prop_refs_json": prop_refs,
        "costume_refs_json": costume_refs,
        "style_refs_json": style_refs,
        "image_candidates_json": image_candidates,
        "video_variants_json": video_variants,
        # Compatibility fields used by frontend:
        "character_refs": character_refs,
        "scene_refs": scene_refs,
        "prop_refs": prop_refs,
        "costume_refs": costume_refs,
        "style_refs": style_refs,
        "image_candidates": image_candidates,
        "video_variants": video_variants,
        "selected_image": row.selected_image,
        "selected_video": row.selected_video,
        "last_error": row.last_error,
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at),
    }
    normalized["director_preflight"] = analyze_shot_risk(normalized)
    if project_id:
        normalized["prompt_revision"] = revision_public_payload(project_id, int(row.shot_index))
    return normalized


def _shot_row_to_preflight_payload(row: Any) -> dict[str, Any]:
    return {
        "shot_index": row.shot_index,
        "prompt": row.prompt,
        "duration": row.duration,
        "status": row.status,
        "selected": row.selected,
        "character_refs_json": row.character_refs_json or [],
        "scene_refs_json": row.scene_refs_json or [],
        "prop_refs_json": getattr(row, "prop_refs_json", None) or [],
        "costume_refs_json": getattr(row, "costume_refs_json", None) or [],
        "style_refs_json": row.style_refs_json or [],
        "image_candidates_json": row.image_candidates_json or [],
        "video_variants_json": row.video_variants_json or [],
        "selected_image": row.selected_image,
        "selected_video": row.selected_video,
        "last_error": row.last_error,
    }


async def _fetch_project_tasks_for_agent_gate(db: AsyncSession, *, project_id: str, user_id: int) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT task_id::text AS task_id, project_id, run_id::text AS run_id, user_id,
                   task_type, status, progress, stage_text, error_message,
                   credits_reserved, created_at, updated_at, completed_at
            FROM tasks
            WHERE project_id = :project_id
              AND user_id = :user_id
            ORDER BY created_at DESC
            LIMIT 200
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    return [dict(row) for row in result.mappings().all()]


async def _ensure_project_owner(db: AsyncSession, project_id: str, user_id: int) -> None:
    result = await db.execute(
        text("SELECT 1 FROM projects WHERE project_id = :project_id AND user_id = :user_id"),
        {"project_id": project_id, "user_id": user_id},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Project not found")


async def _fetch_shot_rows_for_edit(db: AsyncSession, project_id: str, user_id: int) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT shot_index, prompt, duration, status, selected_video
            FROM shot_rows
            WHERE project_id = :project_id AND user_id = :user_id
            ORDER BY shot_index ASC
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    return [dict(row) for row in result.mappings().fetchall()]


async def _fetch_saved_final_edit_plan(db: AsyncSession, project_id: str, user_id: int) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT plan_json
            FROM final_edit_plans
            WHERE project_id = :project_id AND user_id = :user_id
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    row = result.fetchone()
    if not row or not isinstance(row.plan_json, dict):
        return None
    return row.plan_json


async def _fetch_visual_plan_payload(
    db: AsyncSession,
    project_id: str,
    user_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    shot_result = await db.execute(
        text(
            """
            SELECT shot_index, prompt, duration, status, selected,
                   character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json,
                   image_candidates_json, selected_image,
                   video_variants_json, selected_video, last_error,
                   created_at, updated_at
            FROM shot_rows
            WHERE project_id = :project_id AND user_id = :user_id
            ORDER BY shot_index ASC
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    asset_result = await db.execute(
        text(
            """
            SELECT asset_id, asset_type, file_path, file_url, metadata_json, status, created_at, updated_at
            FROM assets
            WHERE project_id = :project_id AND user_id = :user_id AND status = 'active'
            ORDER BY created_at DESC
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    shots = [_normalize_shot_row_row(row, project_id=project_id) for row in shot_result.fetchall()]
    assets = [_normalize_asset_row(row) for row in asset_result.fetchall()]
    return shots, assets, build_visual_plan(shots, assets)


async def _fetch_shot_row_for_revision(db: AsyncSession, project_id: str, user_id: int, idx: int) -> Any:
    result = await db.execute(
        text(
            """
            SELECT shot_index, prompt, duration, status, selected,
                   character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json,
                   image_candidates_json, selected_image,
                   video_variants_json, selected_video, last_error,
                   created_at, updated_at
            FROM shot_rows
            WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :idx
            """
        ),
        {"project_id": project_id, "user_id": user_id, "idx": idx},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Shot row not found")
    return row


async def _set_shot_prompt(db: AsyncSession, project_id: str, user_id: int, idx: int, prompt: str) -> None:
    result = await db.execute(
        text(
            """
            UPDATE shot_rows
            SET prompt = :prompt, updated_at = NOW()
            WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :idx
            """
        ),
        {"project_id": project_id, "user_id": user_id, "idx": idx, "prompt": prompt},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Shot row not found")


async def _sync_shot_to_workspace_file(
    project_id: str,
    shot_index: int,
    rewritten_prompt: str,
    preflight: dict,
) -> None:
    """同步单个镜头改写后的 prompt 到 workspace shots JSON 文件。

    大脑 _collect_risks 从 workspace 文件读取镜头数据，
    仅更新 DB 而不更新文件会导致大脑继续判定为 blocked。
    """
    from app.services.project_workspace import project_workspace_root
    import json as _json

    root = project_workspace_root(project_id)
    shots_dir = root / "shots"
    if not shots_dir.exists():
        return
    for json_path in shots_dir.glob("*.json"):
        try:
            with open(json_path, encoding="utf-8") as f:
                data = _json.load(f)
        except (OSError, _json.JSONDecodeError):
            continue
        shots = data.get("shots") if isinstance(data.get("shots"), list) else []
        updated = False
        for shot in shots:
            if int(shot.get("shot_index") or 0) == shot_index:
                shot["prompt"] = rewritten_prompt
                if preflight:
                    shot["director_preflight"] = preflight
                updated = True
                break
        if updated:
            with open(json_path, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
            break


async def _upsert_brain_continue_shot_rows(
    db: AsyncSession,
    project_id: str,
    user_id: int,
    shot_rows: list[dict[str, Any]],
) -> None:
    for row in shot_rows:
        if not isinstance(row, dict):
            continue
        shot_index = int(row.get("shot_index") or row.get("shot_number") or 0)
        if shot_index <= 0:
            continue
        await db.execute(
            text(
                """
                INSERT INTO shot_rows (
                    project_id, user_id, shot_index, prompt, duration, status, selected,
                    character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json,
                    image_candidates_json, selected_image, video_variants_json, selected_video, last_error
                )
                VALUES (
                    :project_id, :user_id, :shot_index, :prompt, :duration, :status, :selected,
                    CAST(:character_refs_json AS JSONB), CAST(:scene_refs_json AS JSONB),
                    CAST(:prop_refs_json AS JSONB), CAST(:costume_refs_json AS JSONB),
                    CAST(:style_refs_json AS JSONB), CAST(:image_candidates_json AS JSONB),
                    :selected_image, CAST(:video_variants_json AS JSONB), :selected_video, :last_error
                )
                ON CONFLICT (project_id, shot_index) DO UPDATE
                SET user_id = EXCLUDED.user_id,
                    prompt = EXCLUDED.prompt,
                    duration = EXCLUDED.duration,
                    status = EXCLUDED.status,
                    selected = EXCLUDED.selected,
                    character_refs_json = EXCLUDED.character_refs_json,
                    scene_refs_json = EXCLUDED.scene_refs_json,
                    prop_refs_json = EXCLUDED.prop_refs_json,
                    costume_refs_json = EXCLUDED.costume_refs_json,
                    style_refs_json = EXCLUDED.style_refs_json,
                    image_candidates_json = EXCLUDED.image_candidates_json,
                    selected_image = COALESCE(EXCLUDED.selected_image, shot_rows.selected_image),
                    video_variants_json = EXCLUDED.video_variants_json,
                    selected_video = COALESCE(EXCLUDED.selected_video, shot_rows.selected_video),
                    last_error = EXCLUDED.last_error,
                    updated_at = NOW()
                """
            ),
            {
                "project_id": project_id,
                "user_id": user_id,
                "shot_index": shot_index,
                "prompt": str(row.get("prompt") or row.get("scene_description") or row.get("raw_text") or ""),
                "duration": float(row.get("duration") or row.get("duration_seconds") or 5.0),
                "status": str(row.get("status") or "pending"),
                "selected": bool(row.get("selected") or False),
                "character_refs_json": _json_list_param(row.get("character_refs_json", row.get("character_refs"))),
                "scene_refs_json": _json_list_param(row.get("scene_refs_json", row.get("scene_refs"))),
                "prop_refs_json": _json_list_param(row.get("prop_refs_json", row.get("prop_refs"))),
                "costume_refs_json": _json_list_param(row.get("costume_refs_json", row.get("costume_refs"))),
                "style_refs_json": _json_list_param(row.get("style_refs_json", row.get("style_refs"))),
                "image_candidates_json": _json_list_param(row.get("image_candidates_json", row.get("image_candidates"))),
                "selected_image": row.get("selected_image"),
                "video_variants_json": _json_list_param(row.get("video_variants_json", row.get("video_variants"))),
                "selected_video": row.get("selected_video"),
                "last_error": row.get("last_error"),
            },
        )


def _json_list_param(value: Any) -> str:
    return json.dumps(value if isinstance(value, list) else [], ensure_ascii=False, default=str)


async def _refresh_run_brain_snapshot_after_writeback(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    brain: dict[str, Any],
    mode: str,
) -> None:
    context = brain.get("context") if isinstance(brain.get("context"), dict) else {}
    production_ledger = context.get("production_ledger") if isinstance(context.get("production_ledger"), dict) else {}
    await db.execute(
        text(
            """
            UPDATE agent_runs
            SET production_ledger = CAST(:production_ledger AS JSONB),
                updated_at = NOW()
            WHERE id = CAST(:run_id AS UUID)
              AND project_id = :project_id
              AND user_id = :user_id
            """
        ),
        {
            "run_id": run_id,
            "project_id": project_id,
            "user_id": user_id,
            "production_ledger": json.dumps(production_ledger, ensure_ascii=False, default=str),
        },
    )
    await emit_brain_snapshot_steps(
        db=db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        brain=brain,
        mode=mode,
    )


@router.post("")
async def create_project(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    project_id = uuid.uuid4().hex[:16]
    name = body.get("name", "")
    input_path = body.get("input_path")

    await db.execute(
        text(
            """
            INSERT INTO projects (project_id, user_id, name, input_path)
            VALUES (:project_id, :user_id, :name, :input_path)
            """
        ),
        {"project_id": project_id, "user_id": user_id, "name": name, "input_path": input_path},
    )
    await db.commit()
    workspace = init_project_workspace(project_id, name=name)
    return {"project_id": project_id, "name": name, "status": "active", "workspace": workspace}


@router.get("")
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    offset = (page - 1) * page_size

    count_result = await db.execute(
        text("SELECT COUNT(*) FROM projects WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
    total = count_result.scalar()

    result = await db.execute(
        text(
            """
            SELECT project_id, name, status, progress, error_message, created_at, updated_at
            FROM projects
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"user_id": user_id, "limit": page_size, "offset": offset},
    )
    rows = result.fetchall()
    items = [
        {
            "project_id": r.project_id,
            "name": r.name,
            "status": r.status,
            "progress": r.progress,
            "error_message": r.error_message,
            "created_at": str(r.created_at),
            "updated_at": str(r.updated_at),
        }
        for r in rows
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    result = await db.execute(
        text(
            """
            SELECT project_id, name, status, progress, input_path, error_message, created_at, updated_at
            FROM projects
            WHERE project_id = :project_id AND user_id = :user_id
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "project_id": row.project_id,
        "name": row.name,
        "status": row.status,
        "progress": row.progress,
        "input_path": row.input_path,
        "error_message": row.error_message,
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at),
    }


@router.get("/{project_id}/workspace")
async def get_project_workspace(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    project = await db.execute(
        text("SELECT name FROM projects WHERE project_id = :project_id AND user_id = :user_id"),
        {"project_id": project_id, "user_id": user_id},
    )
    row = project.fetchone()
    return read_project_workspace(project_id, name=str(row.name if row else project_id))


@router.post("/{project_id}/workspace/init")
async def initialize_project_workspace(
    project_id: str,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    project = await db.execute(
        text("SELECT name FROM projects WHERE project_id = :project_id AND user_id = :user_id"),
        {"project_id": project_id, "user_id": user_id},
    )
    row = project.fetchone()
    force = bool((body or {}).get("force"))
    return init_project_workspace(project_id, name=str(row.name if row else project_id), force=force)


@router.post("/{project_id}/workspace/write")
async def write_project_workspace(
    project_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    project = await db.execute(
        text("SELECT name FROM projects WHERE project_id = :project_id AND user_id = :user_id"),
        {"project_id": project_id, "user_id": user_id},
    )
    row = project.fetchone()
    try:
        return write_project_workspace_file(
            project_id,
            relative_path=str((body or {}).get("path") or ""),
            content=str((body or {}).get("content") or ""),
            mode=str((body or {}).get("mode") or "append"),
            source=str((body or {}).get("source") or "director_agent"),
            reason=str((body or {}).get("reason") or ""),
            force=bool((body or {}).get("force")),
            name=str(row.name if row else project_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{project_id}/brain")
async def get_project_brain(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    project = await db.execute(
        text("SELECT name FROM projects WHERE project_id = :project_id AND user_id = :user_id"),
        {"project_id": project_id, "user_id": user_id},
    )
    row = project.fetchone()
    shots_result = await db.execute(
        text(
            """
            SELECT shot_index, prompt, duration, status, selected,
                   character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json,
                   image_candidates_json, selected_image,
                   video_variants_json, selected_video, last_error,
                   created_at, updated_at
            FROM shot_rows
            WHERE project_id = :project_id AND user_id = :user_id
            ORDER BY shot_index ASC
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    operational_shots = [_normalize_shot_row_row(item, project_id=project_id) for item in shots_result.fetchall()]
    final_edit_plan = await _fetch_saved_final_edit_plan(db, project_id, user_id)
    _, _, visual_plan = await _fetch_visual_plan_payload(db, project_id, user_id)
    return build_project_brain(
        project_id,
        name=str(row.name if row else project_id),
        operational_shots=operational_shots,
        final_edit_plan=final_edit_plan,
        visual_plan=visual_plan,
    )


@router.get("/{project_id}/agent-events")
async def get_project_agent_events(
    project_id: str,
    limit: int = Query(100, ge=1, le=300),
    run_id: str | None = Query(None),
    event_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    events = await list_project_agent_events(
        db,
        project_id=project_id,
        user_id=user_id,
        limit=limit,
        run_id=run_id,
        event_type=event_type,
    )
    return {
        "project_id": project_id,
        "events": events,
        "items": events,
        "total": len(events),
    }


@router.get("/{project_id}/logs")
async def get_project_logs(
    project_id: str,
    limit: int = Query(100, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    events = await list_project_agent_events(
        db,
        project_id=project_id,
        user_id=user_id,
        limit=limit,
    )
    return {
        "project_id": project_id,
        "logs": events,
        "events": events,
        "items": events,
        "total": len(events),
    }


@router.get("/{project_id}/agent-runs")
async def get_project_agent_runs(
    project_id: str,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    runs = await list_project_agent_runs(db, project_id=project_id, user_id=user_id, limit=limit)
    return {
        "project_id": project_id,
        "runs": runs,
        "total": len(runs),
    }


@router.post("/{project_id}/production/start")
async def start_video_production(
    project_id: str,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    if not await _project_has_storyboard_shots(db, project_id=project_id, user_id=user_id):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "视频制作需要先完成故事规划和分镜写入。",
                "code": "storyboard_required",
                "action": "production_run",
                "missing": ["shot_rows"],
                "recovery": "generate_story_plan",
                "available_actions": ["generate_story_plan", "ask_human"],
            },
        )
    payload = body or {}
    goal = str(payload.get("goal") or "生成一条15秒短剧预览")
    episode = int(payload.get("episode") or 1)
    scene = int(payload.get("scene") or 1)
    target_duration_sec = int(payload.get("target_duration_sec") or 15)
    mode = str(payload.get("mode") or "step")
    provider_mode = str(payload.get("provider_mode") or "local").strip().lower()
    if provider_mode not in {"local", "real"}:
        provider_mode = "local"
    image_provider = str(payload.get("image_provider") or "seedream").strip().lower()
    video_provider = str(payload.get("video_provider") or "ltx2.3").strip().lower()
    wait_provider_timeout_sec = int(payload.get("wait_provider_timeout_sec") or 1800)
    max_image_tasks = max(1, int(payload.get("max_image_tasks") or 3))
    max_video_tasks = max(1, int(payload.get("max_video_tasks") or 3))
    allowed_max_credits = int(payload.get("allowed_max_credits") or 0)
    agent_run_id = await create_agent_run(
        db,
        project_id=project_id,
        user_id=user_id,
        trigger_type="user_click",
        goal=goal,
        mode=mode,
        estimated_max_credits=0,
        allowed_max_credits=allowed_max_credits,
        production_ledger={
            "target_duration_sec": target_duration_sec,
            "current_episode": episode,
            "current_scene": scene,
        },
        meta={
            "runner": "VideoProductionRunner",
            "dispatch": "dispatch_gateway",
            "compatibility_only": True,
            "compatibility_entry": "production_start",
            "provider_mode": provider_mode,
            "image_provider": image_provider,
            "video_provider": video_provider,
            "clean_start": bool(payload.get("clean_start")),
            "entrypoint": str(payload.get("entrypoint") or ""),
            "input_assets": payload.get("input_assets") if isinstance(payload.get("input_assets"), list) else [],
        },
    )
    return await _dispatch_video_production_run(
        db,
        project_id=project_id,
        user_id=user_id,
        user_tier=str(current_user.get("tier") or "free"),
        payload=payload,
        goal=goal,
        episode=episode,
        scene=scene,
        target_duration_sec=target_duration_sec,
        mode=mode,
        provider_mode=provider_mode,
        image_provider=image_provider,
        video_provider=video_provider,
        wait_provider_timeout_sec=wait_provider_timeout_sec,
        max_image_tasks=max_image_tasks,
        max_video_tasks=max_video_tasks,
        allowed_max_credits=allowed_max_credits,
        agent_run_id=agent_run_id,
    )


async def _dispatch_video_production_run(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    user_tier: str,
    payload: dict[str, Any],
    goal: str,
    episode: int,
    scene: int,
    target_duration_sec: int,
    mode: str,
    provider_mode: str,
    image_provider: str,
    video_provider: str,
    wait_provider_timeout_sec: int,
    max_image_tasks: int,
    max_video_tasks: int,
    allowed_max_credits: int,
    agent_run_id: str,
) -> dict[str, Any]:
    packet = _build_compatibility_decision_packet(
        project_id=project_id,
        run_id=agent_run_id,
        action="video_production_run",
        before={"signals": {"production_target_duration_sec": target_duration_sec}},
        image_unit_price=0,
        video_unit_price=0,
        provider=video_provider,
    )

    async def queue_video_production_run() -> dict[str, Any]:
        return await _queue_video_production_run(
            db,
            project_id=project_id,
            user_id=user_id,
            user_tier=user_tier,
            payload=payload,
            goal=goal,
            episode=episode,
            scene=scene,
            target_duration_sec=target_duration_sec,
            mode=mode,
            provider_mode=provider_mode,
            image_provider=image_provider,
            video_provider=video_provider,
            wait_provider_timeout_sec=wait_provider_timeout_sec,
            max_image_tasks=max_image_tasks,
            max_video_tasks=max_video_tasks,
            allowed_max_credits=allowed_max_credits,
            agent_run_id=agent_run_id,
        )

    return await dispatch_authoritative_packet(
        db,
        packet=packet,
        context=DispatchGatewayContext(
            project_id=project_id,
            user_id=user_id,
            user_tier=user_tier,
            run_id=agent_run_id,
            run_mode=mode,
        ),
        handlers={"video_production_run": queue_video_production_run},
    )


async def _queue_video_production_run(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    user_tier: str,
    payload: dict[str, Any],
    goal: str,
    episode: int,
    scene: int,
    target_duration_sec: int,
    mode: str,
    provider_mode: str,
    image_provider: str,
    video_provider: str,
    wait_provider_timeout_sec: int,
    max_image_tasks: int,
    max_video_tasks: int,
    allowed_max_credits: int,
    agent_run_id: str,
) -> dict[str, Any]:
    production_run = await db.execute(
        text(
            """
            INSERT INTO video_production_runs (
                project_id, user_id, agent_run_id, episode, scene,
                target_duration_sec, status, current_stage, goal
            )
            VALUES (
                :project_id, :user_id, CAST(:agent_run_id AS UUID), :episode, :scene,
                :target_duration_sec, 'queued', 'queued', :goal
            )
            RETURNING id
            """
        ),
        {
            "project_id": project_id,
            "user_id": user_id,
            "agent_run_id": agent_run_id,
            "episode": episode,
            "scene": scene,
            "target_duration_sec": target_duration_sec,
            "goal": goal,
        },
    )
    production_run_id = str(production_run.scalar_one())
    task_id = str(uuid.uuid4())
    task_payload = {
        **payload,
        "project_id": project_id,
        "user_id": user_id,
        "goal": goal,
        "episode": episode,
        "scene": scene,
        "target_duration_sec": target_duration_sec,
        "mode": mode,
        "provider_mode": provider_mode,
        "image_provider": image_provider,
        "video_provider": video_provider,
        "wait_provider_timeout_sec": wait_provider_timeout_sec,
        "max_image_tasks": max_image_tasks,
        "max_video_tasks": max_video_tasks,
        "allowed_max_credits": allowed_max_credits,
        "user_tier": user_tier,
        "agent_run_id": agent_run_id,
        "production_run_id": production_run_id,
    }
    task_payload = adapt_provider_payload(task_payload, task_type="video_production_run", provider="controller")
    await db.execute(
        text(
            """
            INSERT INTO tasks (task_id, user_id, project_id, run_id, task_type, status, priority, payload, credits_reserved)
            VALUES (:task_id, :user_id, :project_id, CAST(:run_id AS UUID), 'video_production_run', 'queued', 3, CAST(:payload AS JSONB), 0)
            """
        ),
        {
            "task_id": task_id,
            "user_id": user_id,
            "project_id": project_id,
            "run_id": agent_run_id,
            "payload": json.dumps(task_payload, ensure_ascii=False, default=str),
        },
    )
    await publish_agent_event(
        db,
        run_id=agent_run_id,
        project_id=project_id,
        user_id=user_id,
        task_id=task_id,
        source="queue",
        event_type="tool_call",
        phase="queued",
        title="派发视频生产 Runner",
        detail=f"production_run_id={production_run_id}",
        status="queued",
        progress=3,
        meta={
            "production_run_id": production_run_id,
            "task_id": task_id,
            "provider_mode": provider_mode,
            "image_provider": image_provider,
            "video_provider": video_provider,
        },
    )
    await db.commit()
    celery_app.send_task(
        "app.tasks.director_tasks.video_production_run_task",
        args=[task_id, str(user_id), task_payload],
        kwargs={"transaction_id": None},
        queue="default",
        priority=3,
    )
    return {
        "production_run_id": production_run_id,
        "agent_run_id": agent_run_id,
        "task_id": task_id,
        "status": "queued",
    }


async def _project_has_storyboard_shots(db: AsyncSession, *, project_id: str, user_id: int) -> bool:
    result = await db.execute(
        text(
            """
            SELECT 1
            FROM shot_rows
            WHERE project_id = :project_id
              AND user_id = :user_id
              AND NULLIF(prompt, '') IS NOT NULL
            LIMIT 1
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    return result.fetchone() is not None


@router.post("/{project_id}/brain/continue")
async def continue_project_brain(
    project_id: str,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    project = await db.execute(
        text("SELECT name FROM projects WHERE project_id = :project_id AND user_id = :user_id"),
        {"project_id": project_id, "user_id": user_id},
    )
    row = project.fetchone()
    shots_result = await db.execute(
        text(
            """
            SELECT shot_index, prompt, duration, status, selected,
                   character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json,
                   image_candidates_json, selected_image,
                   video_variants_json, selected_video, last_error,
                   created_at, updated_at
            FROM shot_rows
            WHERE project_id = :project_id AND user_id = :user_id
            ORDER BY shot_index ASC
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    operational_shots = [_normalize_shot_row_row(item, project_id=project_id) for item in shots_result.fetchall()]
    final_edit_plan = await _fetch_saved_final_edit_plan(db, project_id, user_id)
    _, _, visual_plan = await _fetch_visual_plan_payload(db, project_id, user_id)
    requested_action = str((body or {}).get("action") or "")
    requested_mode = str((body or {}).get("mode") or "step").strip().lower()
    run_mode = requested_mode if requested_mode in {"preview", "step", "autopilot"} else "step"
    stop_after_planning = bool((body or {}).get("_stop_after_planning"))
    current_brain = build_project_brain(
        project_id,
        name=str(row.name if row else project_id),
        goal=str((body or {}).get("goal") or ""),
        operational_shots=operational_shots,
        final_edit_plan=final_edit_plan,
        visual_plan=visual_plan,
    )
    # 优先使用后端实时计算的 next_action，除非前端明确请求的 action 与当前一致
    brain_action = str(current_brain.get("next_action") or "")
    action = brain_action if brain_action else (requested_action or "")
    gate_tasks = await _fetch_project_tasks_for_agent_gate(db, project_id=project_id, user_id=user_id)
    gate = evaluate_action_gate(action, shots=operational_shots, tasks=gate_tasks)
    if not requested_action and action and not gate.get("allowed", True):
        recommendation = recommend_next_action(shots=operational_shots, tasks=gate_tasks)
        if recommendation.get("allowed"):
            action = str(recommendation.get("action") or action)
            gate = evaluate_action_gate(action, shots=operational_shots, tasks=gate_tasks)
    resolved_action = action or "analyze_project"
    image_unit_price = await credit_service.get_price("image_gen")
    video_unit_price = await credit_service.get_price("video_gen_5s")
    estimated_max_credits = _estimate_continue_credits(
        resolved_action,
        operational_shots,
        image_unit=image_unit_price,
        video_unit=video_unit_price,
    )
    production_ledger = (current_brain.get("context") or {}).get("production_ledger") if isinstance(current_brain.get("context"), dict) else {}
    run_id = await create_agent_run(
        db,
        project_id=project_id,
        user_id=user_id,
        trigger_type="user_click",
        goal=str((body or {}).get("goal") or (body or {}).get("instruction") or f"{resolved_action} for project {project_id}"),
        mode=run_mode,
        estimated_max_credits=estimated_max_credits,
        allowed_max_credits=int((body or {}).get("allowed_max_credits") or 0),
        production_ledger=production_ledger if isinstance(production_ledger, dict) else {},
        meta={
                "requested_action": requested_action,
                "resolved_action": resolved_action,
                "requested_intent": (body or {}).get("intent") if isinstance((body or {}).get("intent"), dict) else {},
                "brain_phase": current_brain.get("phase"),
                "next_action": current_brain.get("next_action"),
                "source_run_id": str((body or {}).get("source_run_id") or (body or {}).get("_chain_run_id") or ""),
                "_chain_run_id": str((body or {}).get("_chain_run_id") or ""),
                "human_routing": (body or {}).get("human_routing") if isinstance((body or {}).get("human_routing"), dict) else {},
                "clean_start": bool((body or {}).get("clean_start")),
                "entrypoint": str((body or {}).get("entrypoint") or ""),
                "input_assets": (body or {}).get("input_assets") if isinstance((body or {}).get("input_assets"), list) else [],
            },
    )
    await emit_brain_snapshot_steps(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
            brain=current_brain,
            mode=run_mode,
        )
    await db.commit()

    if run_mode == "preview":
        async with db.begin():
            await update_agent_run(
                db,
                run_id=run_id,
                status="completed",
                current_phase="dispatch_instruction",
                summary="Preview mode analyzed the project without dispatching provider tasks.",
                final_decision=f"next_action={action or '-'}; can_continue={bool(current_brain.get('can_continue'))}",
            )
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source="brain",
                event_type="decision",
                phase="preview_complete",
                title="Preview 模式完成",
                detail="Preview analyzed the next brain action without dispatching provider tasks.",
                status="done",
                progress=100,
                meta={"action": action, "mode": run_mode},
            )
        return {
            "project_id": project_id,
            "applied": False,
            "action": action,
            "mode": run_mode,
            "status": "completed",
            "run_id": run_id,
            "message": "Preview mode completed without dispatching tasks.",
            "before": current_brain,
            "after": current_brain,
        }
    if action in {"generate_keyframes", "plan_visual_assets", "generate_videos", "plan_final_edit"}:
        try:
            return await _dispatch_production_action(
                db,
                action=action,
                project_id=project_id,
                user_id=user_id,
                user_tier=str(current_user.get("tier") or "free"),
                before=current_brain,
                name=str(row.name if row else project_id),
                run_id=run_id,
                run_mode=run_mode,
                result={"project_id": project_id, "before": current_brain},
                image_unit_price=image_unit_price,
                video_unit_price=video_unit_price,
                provider=str((body or {}).get("video_provider") or "ltx2.3"),
                semantic_control={
                    key: (body or {}).get(key)
                    for key in ("intent_brief", "semantic_plan", "constraint_packet", "verification_plan", "human_routing")
                },
            )
        except Exception as exc:
            await update_agent_run(
                db,
                run_id=run_id,
                status="failed",
                current_phase="dispatch_instruction",
                summary=f"Brain continue failed: {exc}",
                final_decision=str(action or ""),
            )
            await db.commit()
            raise
    # --- Bounded planning loop: execute up to MAX_CHAIN planning steps, then dispatch ---
    MAX_CHAIN_STEPS = 3
    chain_step = 0
    current_action = action

    while True:
        instruction = str((body or {}).get("instruction") or "")
        llm_story_understanding = await build_requirement_pipeline(
            instruction,
            project_context={
                "project_id": project_id,
                "project_name": str(row.name if row else project_id),
                "current_action": current_action,
                "brain_phase": current_brain.get("phase"),
            },
        )
        if current_action == "generate_story_plan" and llm_story_understanding.get("mentions_real_work") and not llm_story_understanding.get("sufficient_for_storyboard"):
            missing = llm_story_understanding.get("missing_fields", [])
            understanding_card = llm_story_understanding.get("understanding_card", {})
            question_parts = ["已收到你的需求，但在生成分镜前需要确认以下信息："]
            for field in missing:
                hint = {
                    "work": "具体是哪部作品？",
                    "actor": "主演演员是谁？",
                    "role": "角色名是什么？",
                    "role_identity": "角色的身份/定位？",
                    "story_world": "故事世界观设定？",
                    "scene_anchors": "主要场景地点？",
                    "prop_anchors": "关键道具？",
                    "action_anchors": "核心动作/情节？",
                    "tone_anchors": "风格基调？",
                }.get(field, f"请补充「{field}」")
                question_parts.append(f"- {hint}")
            # 从理解卡中提取已识别的内容作为上下文
            known = {k: v for k, v in understanding_card.items() if v and k in (
                "work", "actor", "role", "role_identity", "story_world"
            ) and str(v).strip() not in ("", "-", "未知", "不明", "待确认", "缺失", "空")}
            if known:
                question_parts.append(f"\n已识别到：{json.dumps(known, ensure_ascii=False)}")
            question_text = "\n".join(question_parts)

            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source=str(llm_story_understanding.get("source") or "story_understanding"),
                event_type="question",
                phase="story_understanding",
                title="需要补充剧情信息",
                detail=question_text,
                status="waiting",
                progress=35,
                meta={"story_understanding": llm_story_understanding},
            )
            await update_agent_run(
                db,
                run_id=run_id,
                status="waiting_for_input",
                current_phase="story_understanding",
                summary=question_text,
                final_decision="awaiting user clarification",
            )
            await db.commit()
            return {
                "status": "waiting_for_input",
                "run_id": run_id,
                "question": question_text,
                "story_understanding": llm_story_understanding,
            }
        try:
            result = continue_project_from_brain(
                project_id,
                action=current_action,
                instruction=instruction,
                name=str(row.name if row else project_id),
                operational_shots=operational_shots,
                story_understanding=llm_story_understanding,
            )
        except Exception as exc:
            await update_agent_run(db, run_id=run_id, status="failed",
                                  current_phase="dispatch_instruction",
                                  summary=f"Brain continue failed at step {chain_step}: {exc}",
                                  final_decision=str(current_action or ""))
            await db.commit()
            raise

        result["run_id"] = run_id
        result["llm_story_understanding"] = llm_story_understanding

        if result.get("applied") and result.get("shot_rows"):
            await _upsert_brain_continue_shot_rows(db, project_id, user_id, result["shot_rows"])
            await db.commit()
            refreshed = await db.execute(
                text(
                    """SELECT shot_index, prompt, duration, status, selected,
                              character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json,
                              image_candidates_json, selected_image,
                              video_variants_json, selected_video, last_error,
                              created_at, updated_at
                       FROM shot_rows
                       WHERE project_id = :project_id AND user_id = :user_id
                       ORDER BY shot_index ASC"""
                ),
                {"project_id": project_id, "user_id": user_id},
            )
            operational_shots = [_normalize_shot_row_row(r, project_id=project_id) for r in refreshed.fetchall()]
            result["after"] = build_project_brain(
                project_id, name=str(row.name if row else project_id),
                operational_shots=operational_shots, final_edit_plan=final_edit_plan, visual_plan=visual_plan,
            )
            await _refresh_run_brain_snapshot_after_writeback(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                brain=result["after"],
                mode=run_mode,
            )
            result["operational_shots"] = operational_shots
            if stop_after_planning and current_action == "generate_story_plan":
                result["stopped_after_planning"] = True

        if not result.get("applied"):
            break

        await publish_agent_event(
            db, run_id=run_id, project_id=project_id, user_id=user_id,
            source="brain", event_type="tool_result", phase="writeback_review",
                        title=f"规划步骤完成：{current_action}",
            detail=str(result.get("message") or "applied"),
            status="done", progress=min(90, 50 + chain_step * 15),
            meta={"action": current_action, "chain_step": chain_step, "story_understanding": llm_story_understanding},
        )

        after_brain = result.get("after") or {}
        after_action = str(after_brain.get("next_action") or "")
        chain_step += 1

        should_chain = _should_continue_planning_chain(
            run_mode=run_mode,
            result=result,
            chain_step=chain_step,
            max_chain_steps=MAX_CHAIN_STEPS,
        )
        if not should_chain:
            break

        await publish_agent_event(
            db, run_id=run_id, project_id=project_id, user_id=user_id,
            source="brain", event_type="decision", phase="dispatch_instruction",
            title=f"链式推进 -> {after_action}",
            detail=f"步骤 {chain_step}/{MAX_CHAIN_STEPS}",
            status="running", progress=50 + chain_step * 10,
            meta={"chained_action": after_action, "chain_step": chain_step},
        )
        await db.commit()
        current_action = after_action

    # --- Post-loop: dispatch production action or finalize ---
    if result.get("applied"):
        after_brain = result.get("after") or {}
        after_action = str(after_brain.get("next_action") or "")
        dispatch_action = _dispatch_action_after_planning(after_brain, after_action)
        if dispatch_action and run_mode != "preview" and not result.get("stopped_after_planning"):
            await update_agent_run(db, run_id=run_id, current_phase="dispatch_instruction",
                                  summary=f"Planning chain done ({chain_step} steps), dispatching {dispatch_action}.")
            await db.commit()
            return await _dispatch_production_action(
                db, action=dispatch_action, project_id=project_id, user_id=user_id,
                user_tier=str(current_user.get("tier") or "free"),
                before=after_brain, name=str(row.name if row else project_id),
                run_id=run_id, run_mode=run_mode, result=result,
                image_unit_price=image_unit_price,
                video_unit_price=video_unit_price,
            )
        await update_agent_run(
            db, run_id=run_id, status="completed", current_phase="writeback_review",
            summary=str(result.get("message") or f"Planning completed ({chain_step} steps)."),
            final_decision=str(result.get("action") or current_action or ""),
        )
    else:
        await publish_agent_event(
            db,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            source="brain",
            event_type="risk",
            phase="dispatch_instruction",
            title="Action not applied",
            detail=str(result.get("message") or "Current action is not supported for automatic execution."),
            status="blocked",
            progress=100,
            meta={"action": action},
        )
        await update_agent_run(
            db,
            run_id=run_id,
            status="blocked",
            current_phase="dispatch_instruction",
            summary=str(result.get("message") or "Action was not applied."),
            final_decision=str(action or ""),
        )
    await db.commit()
    return result


def _dispatch_action_after_planning(after_brain: dict[str, Any], after_action: str) -> str:
    if after_brain.get("can_continue") and after_action in {"generate_keyframes", "plan_visual_assets", "generate_videos", "plan_final_edit"}:
        return after_action
    signals = after_brain.get("signals") if isinstance(after_brain.get("signals"), dict) else {}
    if after_action in {"lock_assets", "plan_scene"} and int(signals.get("operational_pending_keyframe_count") or 0) > 0:
        return "generate_keyframes"
    return ""


def _should_continue_planning_chain(
    *,
    run_mode: str,
    result: dict[str, Any],
    chain_step: int,
    max_chain_steps: int,
) -> bool:
    after_brain = result.get("after") if isinstance(result.get("after"), dict) else {}
    after_action = str(after_brain.get("next_action") or "")
    planning_targets = {"generate_story_plan", "plan_scene", "lock_assets"}
    internal_repair_targets = {"fix_preflight_risks"}
    return (
        run_mode != "preview"
        and not result.get("stopped_after_planning")
        and chain_step <= max_chain_steps
        and (
            (bool(after_brain.get("can_continue")) and after_action in planning_targets)
            or (run_mode == "autopilot" and after_action in internal_repair_targets)
        )
    )


def _build_compatibility_decision_packet(
    *,
    project_id: str,
    run_id: str,
    action: str,
    before: dict[str, Any],
    image_unit_price: int,
    video_unit_price: int,
    provider: str = "ltx2.3",
) -> DecisionTickResult:
    signals = before.get("signals") if isinstance(before.get("signals"), dict) else {}
    lane = {
        "plan_visual_assets": "a_lane_project_brain",
        "generate_keyframes": "c_lane_production",
        "generate_videos": "c_lane_production",
        "plan_final_edit": "c_lane_production",
        "video_production_run": "c_lane_production",
    }.get(action, "main_chain")
    estimated_max_credits = _compatibility_cost_hint(
        action,
        signals=signals,
        image_unit_price=image_unit_price,
        video_unit_price=video_unit_price,
    )
    write_scope = _compatibility_write_scope(action)
    stage_id = {
        "plan_visual_assets": "plan_visual_assets",
        "generate_keyframes": "generate_keyframes",
        "generate_videos": "generate_videos",
        "plan_final_edit": "final_cut",
        "video_production_run": "video_production_run",
    }.get(action, action)
    return DecisionTickResult(
        packet_version="main_run_chain_phase1",
        status="execute",
        action=action,
        stage_id=stage_id,
        selected_lane=lane,
        dispatchable=True,
        allowed=True,
        reason="Legacy brain/continue compatibility wrapper routed through the authoritative dispatch gateway.",
        missing=[],
        fallback_action="request_human_confirmation",
        active_task_count=0,
        failed_task_count=0,
        allowed_writes=write_scope,
        evidence={
            "project_id": project_id,
            "run_id": run_id,
            "shot_count": int(signals.get("workspace_shot_count") or signals.get("operational_shot_count") or 0),
        },
        evidence_refs=[
            {"kind": "shot_rows", "project_id": project_id},
            {"kind": "agent_run", "run_id": run_id},
        ],
        candidate_actions=[{"action": action, "stage_id": stage_id, "status": "pending", "allowed": True, "reason": ""}],
        success_criteria=[],
        budget={
            "unit": "video_gen_5s" if action == "generate_videos" else "image_gen" if action == "generate_keyframes" else "",
            "target_count": _compatibility_target_count(action, signals=signals),
            "estimated_max_credits": estimated_max_credits,
            "source": "workbench_compatibility",
        },
        risk={
            "level": "high" if action == "generate_videos" else "medium" if action in {"generate_keyframes", "plan_final_edit"} else "low",
            "failed_task_count": 0,
            "requires_human": False,
        },
        failure_policy={
            "fallback_action": "request_human_confirmation",
            "retryable": action in {"generate_keyframes", "generate_videos"},
            "require_human_confirmation": False,
        },
        mission={
            "mission_id": f"{run_id}:{action}",
            "lane": lane,
            "action": action,
            "write_scope": write_scope,
            "idempotency_key": f"{run_id}:{action}",
            "provider": provider if action == "generate_videos" else "",
        },
    )


def _compatibility_target_count(action: str, *, signals: dict[str, Any]) -> int:
    if action == "generate_keyframes":
        return min(BRAIN_KEYFRAME_BATCH_MAX, int(signals.get("operational_pending_keyframe_count") or 0))
    if action == "generate_videos":
        return min(BRAIN_VIDEO_BATCH_MAX, int(signals.get("operational_pending_video_count") or 0))
    if action == "video_production_run":
        return 1
    return 0


def _compatibility_cost_hint(
    action: str,
    *,
    signals: dict[str, Any],
    image_unit_price: int,
    video_unit_price: int,
) -> int:
    if action == "generate_keyframes":
        return _compatibility_target_count(action, signals=signals) * image_unit_price
    if action == "generate_videos":
        return _compatibility_target_count(action, signals=signals) * video_unit_price
    return 0


def _compatibility_write_scope(action: str) -> list[str]:
    if action == "video_production_run":
        return ["video_production_runs", "tasks", "agent_events", "agent_runs"]
    if action in {"generate_keyframes", "generate_videos"}:
        return ["tasks", "shot_rows", "agent_events", "agent_runs"]
    if action == "plan_visual_assets":
        return ["asset_refs", "project_workspace", "agent_events", "agent_runs"]
    if action == "plan_final_edit":
        return ["final_edit_plans", "project_workspace", "agent_events", "agent_runs"]
    return []


async def _brain_for_gateway_handler(db: AsyncSession, *, project_id: str, user_id: int) -> dict[str, Any]:
    result = await db.execute(
        text(
            """SELECT shot_index, prompt, duration, status, selected,
                      character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json,
                      image_candidates_json, selected_image,
                      video_variants_json, selected_video, last_error,
                      created_at, updated_at
               FROM shot_rows
               WHERE project_id = :project_id AND user_id = :user_id
               ORDER BY shot_index ASC"""
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    rows = [_normalize_shot_row_row(row, project_id=project_id) for row in result.fetchall()]
    return build_project_brain(project_id, operational_shots=rows)


_REVIEW_TO_GENERATE_ACTION = {
    "review_keyframes": "generate_keyframes",
    "review_videos": "generate_videos",
}

_VALID_PRODUCTION_ACTIONS = {
    "generate_keyframes", "plan_visual_assets",
    "generate_videos", "plan_final_edit",
}


def _resolve_authoritative_dispatch_action(action: str, packet: DecisionTickResult) -> tuple[str, bool]:
    """Return the action to dispatch and whether the decision packet is compatible."""
    if packet.action == action:
        return action, True
    if _REVIEW_TO_GENERATE_ACTION.get(packet.action) == action:
        return action, True
    if packet.action in _VALID_PRODUCTION_ACTIONS and packet.status == "execute":
        return packet.action, True
    return action, False


async def _dispatch_production_action(
    db: AsyncSession,
    *,
    action: str,
    project_id: str,
    user_id: int,
    user_tier: str,
    before: dict[str, Any],
    name: str,
    run_id: str,
    run_mode: str,
    result: dict[str, Any],
    image_unit_price: int,
    video_unit_price: int,
    provider: str = "ltx2.3",
    semantic_control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route a production-stage action to its handler after planning loop completes."""
    facts = await load_run_facts_from_snapshot(db, run_id=run_id, user_id=user_id)
    if facts is None:
        packet = _build_compatibility_decision_packet(
            project_id=project_id,
            run_id=run_id,
            action=action,
            before=before,
            image_unit_price=image_unit_price,
            video_unit_price=video_unit_price,
            provider=provider,
        )
    else:
        packet = evaluate_decision_tick(facts)
        action, compatible = _resolve_authoritative_dispatch_action(action, packet)
        if not compatible:
            # Allow review→generate compatibility
            if False:
                # 大脑与状态机判断不一致时，自动跟随状态机的 canonical_action
                action = packet.action
            elif packet.status == "blocked":
                # Gate recovery: when the state machine blocks, find what action
                # would unblock the gate and redirect to it.
                from app.services.agent_run_state_machine import _gate_recovery
                recovery = _gate_recovery({
                    "action": packet.action,
                    "status": packet.status,
                    "gate": {"missing": packet.missing},
                })
                if recovery and recovery in _VALID_PRODUCTION_ACTIONS:
                    action = recovery
                    # Re-evaluate to get an updated packet for this action
                    packet = _build_compatibility_decision_packet(
                        project_id=project_id,
                        run_id=run_id,
                        action=action,
                        before=before,
                        image_unit_price=image_unit_price,
                        video_unit_price=video_unit_price,
                        provider=provider,
                    )
                else:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "decision_action_mismatch",
                            "requested_action": action,
                            "canonical_action": packet.action,
                            "status": packet.status,
                            "gate_recovery": recovery,
                        },
                    )
            else:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "decision_action_mismatch",
                        "requested_action": action,
                        "canonical_action": packet.action,
                        "status": packet.status,
                    },
                )
    handlers = {
        "generate_keyframes": lambda: _continue_generate_keyframes(
            db,
            project_id=project_id,
            user_id=user_id,
            user_tier=user_tier,
            before=before,
            run_id=run_id,
            semantic_control=semantic_control,
        ),
        "plan_visual_assets": lambda: _continue_plan_visual_assets(
            db,
            project_id=project_id,
            user_id=user_id,
            before=before,
            name=name,
            run_id=run_id,
        ),
        "generate_videos": lambda: _continue_generate_videos(
            db,
            project_id=project_id,
            user_id=user_id,
            user_tier=user_tier,
            before=before,
            run_id=run_id,
            provider=provider,
            semantic_control=semantic_control,
        ),
        "plan_final_edit": lambda: _continue_plan_final_edit(
            db,
            project_id=project_id,
            user_id=user_id,
            before=before,
            name=name,
            run_id=run_id,
        ),
    }
    return await dispatch_authoritative_packet(
        db,
        packet=packet,
        context=DispatchGatewayContext(
            project_id=project_id,
            user_id=user_id,
            user_tier=user_tier,
            run_id=run_id,
            run_mode=run_mode,
            runtime_features=_runtime_features_for_production_action(action),
            provider_capabilities=_provider_capabilities_for_production_action(action, provider=provider),
            capability_versions=_capability_versions_for_production_action(action),
        ),
        handlers=handlers,
    )


def _runtime_features_for_production_action(action: str) -> list[str]:
    if action == "generate_videos":
        return [
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        ]
    if action == "plan_final_edit":
        return [
            "scene_analysis",
            "selected_video_read",
            "final_edit_plan_writeback",
        ]
    return []


def _provider_capabilities_for_production_action(action: str, *, provider: str = "") -> list[str]:
    if action == "generate_videos":
        p = str(provider or "").strip().lower()
        if p == "seedance":
            return ["seedance_image_to_video"]
        # LTX / legacy Wan / ComfyUI are image-to-video providers.
        return ["seedance_image_to_video"]
    return []


def _capability_versions_for_production_action(action: str) -> dict[str, str]:
    if action in {"generate_videos", "plan_final_edit"}:
        return {action: "2026-05-27.v1"}
    return {}


def _evaluate_showrunner_generation_preflight(
    *,
    before: dict[str, Any],
    name: str,
    targets: list[dict[str, Any]],
    action: str,
    run_id: str = "",
) -> ShowrunnerDecision:
    context = before.get("context") if isinstance(before.get("context"), dict) else {}
    goal_text = _showrunner_goal_text(before=before, name=name)
    goal_card = build_goal_card(goal_text, project_name=name, context=context)
    _, decision = judge_generation_preflight(
        goal_card,
        targets,
        run_id=run_id,
        stage_id=str(action or "generate_keyframes"),
    )
    return decision


def _showrunner_goal_text(*, before: dict[str, Any], name: str) -> str:
    context = before.get("context") if isinstance(before.get("context"), dict) else {}
    parts = [
        str(context.get("project") or ""),
        str(context.get("episodes") or ""),
        str(context.get("scene") or ""),
        str(context.get("decisions") or ""),
        str(before.get("summary") or ""),
        str(name or ""),
    ]
    return "\n".join(part for part in parts if part.strip())


async def _guard_showrunner_generation_preflight(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    run_id: str | None,
    before: dict[str, Any],
    name: str,
    targets: list[dict[str, Any]],
    action: str,
) -> None:
    decision = _evaluate_showrunner_generation_preflight(
        before=before,
        name=name,
        targets=targets,
        action=action,
        run_id=str(run_id or ""),
    )
    if decision.status == "execute":
        return

    meta = decision.as_dict()
    if run_id:
        await publish_agent_event(
            db,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            source="showrunner",
            event_type="decision",
            phase="showrunner_preflight",
            title="Showrunner blocked provider dispatch",
            detail=decision.reason,
            status=decision.status,
            progress=50,
            meta=meta,
            event_kind="decision",
            visibility="debug",
            summary=f"Showrunner {decision.status}: {decision.action}",
            reason=decision.reason,
        )
        await update_agent_run(
            db,
            run_id=run_id,
            status="blocked",
            current_phase="showrunner_preflight",
            summary=f"Showrunner blocked {action}: {decision.reason}",
            final_decision=decision.action,
        )
        await db.commit()

    raise HTTPException(
        status_code=409,
        detail={
            "error": "showrunner_preflight_blocked",
            "message": "Showrunner blocked provider dispatch before spending credits.",
            "decision": meta,
        },
    )


async def _continue_plan_visual_assets(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    before: dict[str, Any],
    name: str = "",
    run_id: str | None = None,
) -> dict[str, Any]:
    _, _, plan = await _fetch_visual_plan_payload(db, project_id, user_id)
    actions = [item for item in plan.get("asset_actions", []) if isinstance(item, dict)]
    if not actions:
        raise HTTPException(status_code=400, detail="No visual asset actions are currently needed")

    applied: list[dict[str, Any]] = []
    created_count = 0
    bound_count = 0
    reused_planned_count = 0
    planned_reference_by_group: dict[str, str] = {}
    try:
        for action in actions:
            requested_asset_id = ""
            if action.get("action_type") == "generate_reference":
                group_key = _visual_reference_group_key(action)
                requested_asset_id = planned_reference_by_group.get(group_key, "")
            result = await _apply_visual_plan_action_to_db(
                db,
                project_id,
                user_id,
                action,
                requested_asset_id=requested_asset_id,
            )
            applied.append(result)
            if result.get("created_asset"):
                created_count += 1
                planned_reference_by_group[_visual_reference_group_key(action)] = str(result.get("asset_id") or "")
            elif action.get("action_type") == "generate_reference":
                reused_planned_count += 1
            else:
                bound_count += 1
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    write_project_workspace_file(
        project_id,
        relative_path="memory/decisions.md",
        content=(
            "\n## Visual Asset Plan\n\n"
            f"- actions: {len(applied)}\n"
            f"- bind_existing: {bound_count}\n"
            f"- planned_references: {created_count}\n"
            f"- reused_planned_reference_bindings: {reused_planned_count}\n"
            "- source: project_brain_continue\n"
            "- reason: compress Seedream reference demand by locking reusable master references before keyframes\n"
        ),
        mode="append",
        source="project_brain_continue",
        reason="continue action: plan_visual_assets",
        name=name or project_id,
    )

    refreshed_shots, _, refreshed_plan = await _fetch_visual_plan_payload(db, project_id, user_id)
    after = build_project_brain(
        project_id,
        name=name or project_id,
        operational_shots=refreshed_shots,
        final_edit_plan=await _fetch_saved_final_edit_plan(db, project_id, user_id),
        visual_plan=refreshed_plan,
    )
    if run_id:
        await publish_agent_event(
            db,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            source="brain",
            event_type="tool_result",
            phase="plan_visual_assets",
            title="视觉资产规划完成",
            detail=f"处理 {len(applied)} 个动作，复用 {bound_count} 个已有资产，新增 {created_count} 个计划参考。",
            status="done",
            progress=100,
            meta={"applied_count": len(applied), "bound_existing_count": bound_count, "planned_reference_count": created_count},
        )
        await update_agent_run(
            db,
            run_id=run_id,
            status="completed",
            current_phase="writeback_review",
            summary="Visual asset planning completed.",
            final_decision="planned visual assets before provider generation",
        )
        await db.commit()
    return {
        "project_id": project_id,
        "run_id": run_id,
        "applied": True,
        "action": "plan_visual_assets",
        "message": "Visual asset plan applied.",
        "before": before,
        "after": after,
        "applied_actions": applied,
        "applied_count": len(applied),
        "bound_existing_count": bound_count,
        "planned_reference_count": created_count,
        "reused_planned_reference_count": reused_planned_count,
        "compressed_reference_group_count": len(planned_reference_by_group),
        "visual_plan": refreshed_plan,
    }


async def _continue_plan_final_edit(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    before: dict[str, Any],
    name: str = "",
    run_id: str | None = None,
) -> dict[str, Any]:
    shot_rows = await _fetch_shot_rows_for_edit(db, project_id, user_id)
    if not shot_rows:
        raise HTTPException(status_code=400, detail="No shot rows available for final edit planning")

    usable_rows, missing_video = _split_final_edit_rows(shot_rows)
    if not usable_rows:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "final_edit_missing_videos",
                "message": "Final edit planning requires at least one shot row to have selected_video.",
                "missing_shot_indices": missing_video,
            },
        )

    saved_plan = await _fetch_saved_final_edit_plan(db, project_id, user_id)
    plan = merge_plan_with_shots(saved_plan, usable_rows) if saved_plan else build_default_edit_plan(usable_rows)
    plan = normalize_edit_plan(plan)
    plan["settings"] = {
        **(plan.get("settings") if isinstance(plan.get("settings"), dict) else {}),
        "partial_edit": bool(missing_video),
        "missing_video_shot_indices": missing_video,
    }
    if not plan.get("clips"):
        raise HTTPException(status_code=400, detail="No usable video clips available for final edit planning")

    await db.execute(
        text(
            """
            INSERT INTO final_edit_plans (project_id, user_id, plan_json)
            VALUES (:project_id, :user_id, CAST(:plan_json AS JSONB))
            ON CONFLICT (project_id, user_id)
            DO UPDATE SET plan_json = EXCLUDED.plan_json, updated_at = NOW()
            """
        ),
        {
            "project_id": project_id,
            "user_id": user_id,
            "plan_json": json.dumps(plan, ensure_ascii=False),
        },
    )
    await db.commit()

    write_project_workspace_file(
        project_id,
        relative_path="memory/decisions.md",
        content=(
            "\n## Final Edit Plan\n\n"
            f"- clips: {len(plan.get('clips') or [])}\n"
            f"- missing_videos: {missing_video}\n"
            "- source: project_brain_continue\n"
            "- next: open /director/final-cut to generate preview and export final video\n"
        ),
        mode="append",
        source="project_brain_continue",
        reason="continue action: plan_final_edit",
        name=name or project_id,
    )

    after = build_project_brain(
        project_id,
        name=name or project_id,
        operational_shots=[
            {
                **row,
                "selected_video": row.get("selected_video"),
                "status": row.get("status"),
            }
            for row in shot_rows
        ],
        final_edit_plan=plan,
    )
    if run_id:
        await record_agent_artifact(
            db,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            artifact_type="edit_plan",
            uri=f"/director/final-cut/{project_id}",
            summary=f"Final edit plan saved with {len(plan.get('clips') or [])} clips.",
            meta={"clip_count": len(plan.get("clips") or []), "partial_edit": bool(missing_video), "missing_shot_indices": missing_video},
        )
        await update_agent_run(
            db,
            run_id=run_id,
            status="completed",
            current_phase="writeback_review",
            summary="Final edit plan saved." if not missing_video else f"Partial final edit plan saved; missing videos for shots {missing_video}.",
            final_decision="open final cut for preview/export",
        )
        await db.commit()
    return {
        "project_id": project_id,
        "run_id": run_id,
        "applied": True,
        "action": "plan_final_edit",
        "message": "Final edit plan saved.",
        "before": before,
        "after": after,
        "plan": plan,
        "partial_edit": bool(missing_video),
        "missing_shot_indices": missing_video,
        "clip_count": len(plan.get("clips") or []),
        "final_cut_url": f"/director/final-cut/{project_id}",
    }


def _split_final_edit_rows(shot_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[int]]:
    usable_rows: list[dict[str, Any]] = []
    missing_video: list[int] = []
    for row in shot_rows:
        if str(row.get("selected_video") or "").strip():
            usable_rows.append(row)
            continue
        try:
            missing_video.append(int(row.get("shot_index") or 0))
        except (TypeError, ValueError):
            missing_video.append(0)
    return usable_rows, missing_video


def _guard_keyframe_preflight(items: list[dict[str, Any]]) -> None:
    blocked = [item for item in items if isinstance(item.get("director_preflight"), dict) and item["director_preflight"].get("risk_level") == "blocked"]
    if blocked:
        indices = [str(item.get("shot_index") or "?") for item in blocked[:5]]
        raise HTTPException(status_code=400, detail=f"Shots {', '.join(indices)} have blocked preflight risks")


def _guard_video_preflight(items: list[dict[str, Any]]) -> None:
    blocked = [item for item in items if isinstance(item.get("director_preflight"), dict) and item["director_preflight"].get("risk_level") == "blocked"]
    if blocked:
        indices = [str(item.get("shot_index") or "?") for item in blocked[:5]]
        raise HTTPException(status_code=400, detail=f"Shots {', '.join(indices)} have blocked preflight risks")
    missing_image = [item for item in items if not item.get("selected_image")]
    if missing_image:
        indices = [str(item.get("shot_index") or "?") for item in missing_image[:5]]
        raise HTTPException(status_code=400, detail=f"Shots {', '.join(indices)} missing selected_image for video generation")


def _keyframe_generation_targets(
    rows: list[dict[str, Any]],
    *,
    semantic_control: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    repair = _keyframe_review_repair_request(semantic_control)
    if not repair:
        missing = [
            r for r in rows
            if r.get("prompt") and not r.get("selected_image")
            and str(r.get("status") or "") not in {"generating_image", "generating_video", "video_done"}
        ]
        expired = [
            {
                **r,
                "regeneration": {
                    "reason": "selected_image_url_expired",
                    "recommendation": "regenerate_expired_keyframe_url",
                    "previous_selected_image": r.get("selected_image") or "",
                },
            }
            for r in rows
            if r.get("prompt") and r.get("selected_image")
            and _signed_media_url_expired(str(r.get("selected_image") or ""))
            and str(r.get("status") or "") not in {"generating_image", "generating_video", "video_done"}
        ]
        return missing + expired
    shot_indices = {_safe_int(item) for item in repair.get("shot_indices") or [] if _safe_int(item) > 0}
    targets: list[dict[str, Any]] = []
    for row in rows:
        shot_index = _safe_int(row.get("shot_index"))
        if shot_indices and shot_index not in shot_indices:
            continue
        if not row.get("prompt") or not row.get("selected_image"):
            continue
        if str(row.get("status") or "") in {"generating_image", "generating_video", "video_done"}:
            continue
        if _image_review_status(row) not in {"needs_review", "regenerate", "failed", "fail", "rejected", "blocked"}:
            continue
        targets.append(
            {
                **row,
                "regeneration": {
                    "reason": "image_review_blockers",
                    "recommendation": "regenerate_review_failed_keyframes",
                    "previous_selected_image": row.get("selected_image") or "",
                    "default_instruction": str(repair.get("default_instruction") or ""),
                },
            }
        )
    return targets


def _keyframe_review_repair_request(semantic_control: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(semantic_control, dict):
        return None
    routing = semantic_control.get("human_routing") if isinstance(semantic_control.get("human_routing"), dict) else {}
    pending = routing.get("pending_action") if isinstance(routing.get("pending_action"), dict) else {}
    candidates = (pending, routing.get("review_blocker_clarification", {}).get("proposal") if isinstance(routing.get("review_blocker_clarification"), dict) else {})
    for candidate in candidates:
        if isinstance(candidate, dict) and str(candidate.get("recommendation") or "") == "regenerate_review_failed_keyframes":
            return candidate
    return None


def _image_review_status(row: dict[str, Any]) -> str:
    selected = str(row.get("selected_image") or "").strip()
    candidates = row.get("image_candidates")
    if candidates is None:
        candidates = row.get("image_candidates_json")
    values = candidates if isinstance(candidates, list) else [candidates] if candidates else []
    fallback = ""
    for candidate in values:
        if not isinstance(candidate, dict):
            continue
        review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
        status = str(candidate.get("review_status") or candidate.get("status") or review.get("status") or "").strip().lower()
        if not status:
            continue
        url = str(candidate.get("url") or candidate.get("uri") or candidate.get("image_url") or "").strip()
        if selected and url == selected:
            return status
        fallback = fallback or status
    return fallback


def _signed_media_url_expired(url: str, *, now: datetime | None = None) -> bool:
    value = str(url or "").strip()
    if not value:
        return False
    query = parse_qs(urlparse(value).query)
    expires_values = query.get("Expires") or query.get("expires")
    if expires_values:
        try:
            return int(expires_values[0]) <= int((now or datetime.now(timezone.utc)).timestamp())
        except (TypeError, ValueError):
            return False
    tos_dates = query.get("X-Tos-Date") or query.get("x-tos-date")
    tos_expires = query.get("X-Tos-Expires") or query.get("x-tos-expires")
    if tos_dates and tos_expires:
        try:
            ttl_seconds = int(tos_expires[0])
            if ttl_seconds > 7 * 24 * 60 * 60:
                return False
            issued_at = datetime.strptime(tos_dates[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return issued_at + timedelta(seconds=ttl_seconds) <= (now or datetime.now(timezone.utc))
        except (TypeError, ValueError):
            return False
    return False


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


async def _continue_generate_batch(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    user_tier: str,
    before: dict[str, Any],
    run_id: str | None = None,
    media_type: str,
    provider: str = "seedream",
    semantic_control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Unified batch generation for keyframes and videos.

    media_type: "keyframe" or "video"
    """
    is_video = media_type == "video"
    task_type = "video_gen" if is_video else "image_gen"
    operation = "video_gen_5s" if is_video else "image_gen"
    batch_max = BRAIN_VIDEO_BATCH_MAX if is_video else BRAIN_KEYFRAME_BATCH_MAX
    status_generating = "generating_video" if is_video else "generating_image"
    queue_name = "video" if is_video else "image"
    celery_task_name = "app.tasks.video_tasks.generate_video_task" if is_video else "app.tasks.image_tasks.generate_image_task"
    action_name = "generate_videos" if is_video else "generate_keyframes"

    rows_result = await db.execute(
        text(
            """SELECT shot_index, prompt, duration, status, selected,
                      character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json,
                      image_candidates_json, selected_image,
                      video_variants_json, selected_video, last_error,
                      created_at, updated_at
               FROM shot_rows
               WHERE project_id = :project_id AND user_id = :user_id
               ORDER BY shot_index ASC"""
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    rows = [_normalize_shot_row_row(item, project_id=project_id) for item in rows_result.fetchall()]

    if is_video:
        generating = [r for r in rows if "generating" in str(r.get("status") or "") or "running" in str(r.get("status") or "")]
        if generating:
            raise HTTPException(status_code=409, detail="Some shots are still generating. Wait for write-back.")
        targets = [
            r for r in rows
            if r.get("prompt") and r.get("selected_image") and not r.get("selected_video")
            and str(r.get("status") or "") not in {"generating_video", "video_done", "done", "final_done", "exported"}
        ]
    else:
        targets = _keyframe_generation_targets(rows, semantic_control=semantic_control)

    if not targets:
        raise HTTPException(status_code=400, detail=f"No eligible shots for {media_type} generation")
    targets = targets[:batch_max]

    await _guard_showrunner_generation_preflight(
        db,
        project_id=project_id,
        user_id=user_id,
        run_id=run_id,
        before=before,
        name=project_id,
        targets=targets,
        action=action_name,
    )

    if is_video:
        _guard_video_preflight(targets)
    else:
        _guard_keyframe_preflight(targets)
    await check_concurrent_limit(user_id, user_tier, db)
    await check_rate_limit(user_id, user_tier, task_type.split("_")[0] + "_gen", db)

    # --- Capacity guard: check Key Pool concurrency before dispatching ---
    from app.services.capacity_guard import check_capacity_sync
    capacity = check_capacity_sync(provider)
    dispatch_count = len(targets)
    queued_count = 0
    if capacity.total_concurrency > 0 and capacity.available_slots < dispatch_count:
        dispatch_count = max(1, capacity.available_slots)
        queued_count = len(targets) - dispatch_count
    dispatch_targets = targets[:dispatch_count]
    # ----------------------------------------------------------------

    unit_price = await credit_service.get_price(operation)
    total_cost = len(dispatch_targets) * unit_price
    if not await ensure_run_budget(db, run_id=run_id, project_id=project_id, user_id=user_id, next_cost=total_cost, label=f"queue {len(dispatch_targets)} {media_type} task(s)"):
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Run budget blocked {media_type} generation")
    await assert_cost_guard(db, user_id=user_id, credits_to_reserve=total_cost)

    transaction_ids: list[str] = []
    try:
        for _ in dispatch_targets:
            transaction_ids.append(await reserve_credits(user_id, operation, 1))
    except Exception:
        for tid in transaction_ids:
            await credit_service.refund(tid)
        raise

    priority = {"free": 5, "pro": 3, "enterprise": 1}.get(user_tier, 5)
    parent_task_id = str(uuid.uuid4())
    child_task_ids: list[str] = []
    payloads: list[dict[str, Any]] = []

    # Build shot_index → row lookup for continuity (prev shot reference)
    _shot_by_index: dict[int, dict[str, Any]] = {int(r.get("shot_index", -1)): r for r in rows}

    try:
        for idx, row in enumerate(dispatch_targets):
            child_id = str(uuid.uuid4())
            child_task_ids.append(child_id)
            payload: dict[str, Any] = {
                "provider": provider, "project_id": project_id, "run_id": run_id,
                "shot_index": row["shot_index"], "prompt": row.get("prompt") or "",
                "total_shots": len(rows),
                "shot_row": {**row, "project_id": project_id, "user_id": user_id, "total_shots": len(rows)},
            }
            if semantic_control:
                payload.update({key: value for key, value in semantic_control.items() if value is not None})
            if is_video:
                payload["duration"] = row.get("duration") or 5
                payload["image_url"] = row.get("selected_image") or ""
            # Continuity: inject previous shot's output as reference for temporal coherence
            prev_shot = _shot_by_index.get(int(row["shot_index"]) - 1)
            if prev_shot:
                prev_ref = prev_shot.get("selected_video") or prev_shot.get("selected_image") or ""
                if prev_ref:
                    payload["prev_shot_reference"] = prev_ref
            payload = adapt_provider_payload(payload, task_type=task_type, provider=provider)
            payloads.append(payload)
            await db.execute(
                text("""INSERT INTO tasks (task_id, user_id, project_id, run_id, task_type, status, priority, payload, credits_reserved, credit_transaction_id)
                        VALUES (:tid, :uid, :project_id, CAST(:run_id AS UUID), :task_type, 'queued', :priority, :payload, :credits, :credit_transaction_id)"""),
                {"tid": child_id, "uid": user_id, "project_id": project_id, "run_id": run_id, "priority": priority,
                 "payload": json.dumps({**payload, "_credit_transaction_id": transaction_ids[idx]}, ensure_ascii=False),
                 "credits": unit_price, "credit_transaction_id": transaction_ids[idx], "task_type": task_type},
            )
            await db.execute(
                text("UPDATE shot_rows SET status = :status, updated_at = NOW() WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :shot_index"),
                {"status": status_generating, "project_id": project_id, "user_id": user_id, "shot_index": row["shot_index"]},
            )
        await db.commit()
    except Exception:
        await db.rollback()
        for tid in transaction_ids:
            await credit_service.refund(tid)
        raise

    for idx, child_id in enumerate(child_task_ids):
        celery_app.send_task(celery_task_name, args=[child_id, str(user_id), payloads[idx]], kwargs={"transaction_id": transaction_ids[idx]}, queue=queue_name, priority=priority)

    # Enqueue deferred tasks into work queue for automatic retry when capacity opens
    work_queue_positions: list[int] = []
    if queued_count > 0 and provider:
        from app.services.work_queue import enqueue as work_enqueue
        service = provider  # provider name matches key_pool service name
        for idx, row in enumerate(targets[dispatch_count:], start=dispatch_count):
            child_id = str(uuid.uuid4())
            deferred_payload = {
                "provider": provider, "project_id": project_id, "run_id": run_id,
                "shot_index": row["shot_index"], "prompt": row.get("prompt") or "",
                "shot_row": {**row, "project_id": project_id, "user_id": user_id},
            }
            if semantic_control:
                deferred_payload.update({key: value for key, value in semantic_control.items() if value is not None})
            if is_video:
                deferred_payload["duration"] = row.get("duration") or 5
                deferred_payload["image_url"] = row.get("selected_image") or ""
            deferred_payload = adapt_provider_payload(deferred_payload, task_type=task_type, provider=provider)
            pos = work_enqueue(
                service=service,
                task_id=child_id,
                celery_task=celery_task_name,
                args=[child_id, str(user_id), deferred_payload],
                kwargs={"transaction_id": transaction_ids[idx] if idx < len(transaction_ids) else ""},
                queue=queue_name,
                priority=priority,
            )
            work_queue_positions.append(pos)

    write_project_workspace_file(
        project_id, relative_path="memory/decisions.md", mode="append",
        content=f"\n## Brain Continue {media_type.title()}s\n\n- dispatched: {len(child_task_ids)}\n- deferred: {queued_count}\n- work_queue_positions: {work_queue_positions}\n- shots: {', '.join(str(t.get('shot_index')) for t in dispatch_targets)}\n- batch_cap: {batch_max}\n- source: project_brain_continue\n",
        source="project_brain_continue", reason=f"continue action: {action_name}", name=project_id,
    )

    if run_id:
        await publish_agent_event(db, run_id=run_id, project_id=project_id, user_id=user_id, source="queue", event_type="tool_call", phase="queued",
                                  title=f"派发 {media_type} 任务", detail=f"dispatched={len(child_task_ids)} deferred={queued_count}, credits={total_cost}",
                                  status="queued", progress=55, meta={"tasks_dispatched": len(child_task_ids), "tasks_deferred": queued_count, "work_queue_positions": work_queue_positions, "queue": queue_name, "child_task_ids": child_task_ids})
        await update_agent_run(db, run_id=run_id, status="dispatching", current_phase="dispatching",
                              summary=f"{media_type.title()} generation tasks dispatching.", final_decision=f"queued {len(child_task_ids)} {media_type} task(s)",
                              reserved_credits_delta=total_cost)
        await db.commit()

    refreshed = await db.execute(
        text("""SELECT shot_index, prompt, duration, status, selected, character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json,
                       image_candidates_json, selected_image, video_variants_json, selected_video, last_error, created_at, updated_at
                FROM shot_rows WHERE project_id = :project_id AND user_id = :user_id ORDER BY shot_index ASC"""),
        {"project_id": project_id, "user_id": user_id},
    )
    operational_shots = [_normalize_shot_row_row(item, project_id=project_id) for item in refreshed.fetchall()]
    return {
        "project_id": project_id, "run_id": run_id, "applied": True, "action": action_name,
        "message": f"{media_type.title()} generation tasks queued.",
        "before": before, "after": build_project_brain(project_id, operational_shots=operational_shots),
        "parent_task_id": parent_task_id, "child_task_ids": child_task_ids,
        "queued_count": len(child_task_ids), "deferred_count": queued_count,
        "capacity": {
            "service": capacity.service,
            "total_concurrency": capacity.total_concurrency,
            "available_slots": capacity.available_slots,
            "estimated_wait_sec": capacity.estimated_wait_sec,
        },
        "total_credits_reserved": total_cost, "operational_shots": operational_shots,
    }


async def _continue_generate_keyframes(
    db: AsyncSession, *, project_id: str, user_id: int, user_tier: str, before: dict[str, Any], run_id: str | None = None, semantic_control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await _continue_generate_batch(db, project_id=project_id, user_id=user_id, user_tier=user_tier, before=before, run_id=run_id, media_type="keyframe", semantic_control=semantic_control)


async def _continue_generate_videos(
    db: AsyncSession, *, project_id: str, user_id: int, user_tier: str, before: dict[str, Any], run_id: str | None = None, provider: str = "ltx2.3", semantic_control: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await _continue_generate_batch(db, project_id=project_id, user_id=user_id, user_tier=user_tier, before=before, run_id=run_id, media_type="video", provider=provider, semantic_control=semantic_control)


    await _ensure_project_owner(db, project_id, user_id)
    row = await _fetch_shot_row_for_revision(db, project_id, user_id, idx)
    revision = latest_prompt_revision(project_id, idx)
    requested_revision_id = str((body or {}).get("revision_id") or "").strip()
    if requested_revision_id and (not revision or revision.get("revision_id") != requested_revision_id):
        raise HTTPException(status_code=404, detail="Prompt revision not found or already rolled back")
    if not revision:
        raise HTTPException(status_code=404, detail="No prompt revision available to roll back")

    current_prompt = str(row.prompt or "")
    rewritten_prompt = str(revision.get("rewritten_prompt") or "")
    force = bool((body or {}).get("force"))
    if current_prompt.strip() != rewritten_prompt.strip() and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "prompt_changed_after_rewrite",
                "message": "Current prompt no longer matches the rewritten prompt; pass force=true to roll back anyway.",
                "current_prompt": current_prompt,
                "rewritten_prompt": rewritten_prompt,
            },
        )

    original_prompt = str(revision.get("original_prompt") or "")
    await _set_shot_prompt(db, project_id, user_id, idx, original_prompt)
    rolled_back = mark_prompt_revision_rolled_back(project_id, idx, revision.get("revision_id"))
    await db.commit()
    shot_payload = _shot_row_to_preflight_payload(row)
    return {
        "ok": True,
        "shot_index": idx,
        "prompt": original_prompt,
        "director_preflight": analyze_shot_risk({**shot_payload, "prompt": original_prompt}),
        "prompt_revision": rolled_back,
    }


@router.get("/{project_id}/final-edit-plan")
async def get_final_edit_plan(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    shot_rows = await _fetch_shot_rows_for_edit(db, project_id, user_id)
    result = await db.execute(
        text(
            """
            SELECT plan_json
            FROM final_edit_plans
            WHERE project_id = :project_id AND user_id = :user_id
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    row = result.fetchone()
    if not row:
        plan = build_default_edit_plan(shot_rows)
        return {"project_id": project_id, "plan": plan, "source": "default"}
    return {
        "project_id": project_id,
        "plan": merge_plan_with_shots(row.plan_json, shot_rows),
        "source": "saved",
    }


@router.put("/{project_id}/final-edit-plan")
async def save_final_edit_plan(
    project_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    try:
        plan = normalize_edit_plan((body or {}).get("plan") or body or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.execute(
        text(
            """
            INSERT INTO final_edit_plans (project_id, user_id, plan_json)
            VALUES (:project_id, :user_id, CAST(:plan_json AS JSONB))
            ON CONFLICT (project_id, user_id)
            DO UPDATE SET plan_json = EXCLUDED.plan_json, updated_at = NOW()
            """
        ),
        {
            "project_id": project_id,
            "user_id": user_id,
            "plan_json": json.dumps(plan, ensure_ascii=False),
        },
    )
    await db.commit()
    return {"ok": True, "project_id": project_id, "plan": plan}


@router.put("/{project_id}/shot-rows/{idx}")
async def update_shot_row(
    project_id: str,
    idx: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    alias_to_json = {
        "character_refs": "character_refs_json",
        "scene_refs": "scene_refs_json",
        "prop_refs": "prop_refs_json",
        "costume_refs": "costume_refs_json",
        "style_refs": "style_refs_json",
        "image_candidates": "image_candidates_json",
        "video_variants": "video_variants_json",
    }
    allowed = {
        "prompt",
        "duration",
        "status",
        "selected",
        "character_refs_json",
        "scene_refs_json",
        "prop_refs_json",
        "costume_refs_json",
        "style_refs_json",
        "image_candidates_json",
        "selected_image",
        "video_variants_json",
        "selected_video",
        "last_error",
    }

    updates: dict[str, Any] = {}
    for key, value in (body or {}).items():
        normalized_key = alias_to_json.get(key, key)
        if normalized_key in allowed:
            updates[normalized_key] = value

    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    prompt_revision: dict[str, Any] | None = None
    if "prompt" in updates:
        row = await _fetch_shot_row_for_revision(db, project_id, user_id, idx)
        original_prompt = str(row.prompt or "")
        next_prompt = str(updates.get("prompt") or "")
        preflight = analyze_shot_risk(_shot_row_to_preflight_payload(row))
        safe_prompt = str(preflight.get("safe_prompt") or "").strip()
        if safe_prompt and next_prompt.strip() == safe_prompt and next_prompt.strip() != original_prompt.strip():
            prompt_revision = build_prompt_revision(
                shot_index=idx,
                original_prompt=original_prompt,
                rewritten_prompt=next_prompt,
                source=REVISION_SOURCE_DIRECTOR_PREFLIGHT,
                preflight=preflight,
            )

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    params = {**updates, "project_id": project_id, "user_id": user_id, "idx": idx}
    result = await db.execute(
        text(
            f"""
            UPDATE shot_rows
            SET {set_clause}, updated_at = NOW()
            WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :idx
            """
        ),
        params,
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Shot row not found")
    if prompt_revision:
        append_prompt_revision(project_id, prompt_revision)
    await db.commit()
    return {"ok": True, "shot_index": idx, "prompt_revision": prompt_revision}


@router.get("/{project_id}/shot-rows")
async def list_shot_rows(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    result = await db.execute(
        text(
            """
            SELECT shot_index, prompt, duration, status, selected,
                   character_refs_json, scene_refs_json, prop_refs_json, costume_refs_json, style_refs_json,
                   image_candidates_json, selected_image,
                   video_variants_json, selected_video, last_error,
                   created_at, updated_at
            FROM shot_rows
            WHERE project_id = :project_id AND user_id = :user_id
            ORDER BY shot_index ASC
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    return {"project_id": project_id, "items": [_normalize_shot_row_row(row, project_id=project_id) for row in result.fetchall()]}


@router.get("/{project_id}/shot-rows/{idx}")
async def get_shot_row(
    project_id: str,
    idx: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    row = await _fetch_shot_row_for_revision(db, project_id, user_id, idx)
    return _normalize_shot_row_row(row, project_id=project_id)


@router.get("/{project_id}/shot-rows/{idx}/prompt-revisions")
async def list_shot_prompt_revisions(
    project_id: str,
    idx: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _ensure_project_owner(db, project_id, current_user["id"])
    return {
        "project_id": project_id,
        "shot_index": idx,
        "items": list_prompt_revisions(project_id, idx),
        "latest": latest_prompt_revision(project_id, idx),
    }


@router.post("/{project_id}/shot-rows/{idx}/safe-rewrite")
async def apply_shot_safe_rewrite(
    project_id: str,
    idx: int,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    row = await _fetch_shot_row_for_revision(db, project_id, user_id, idx)
    original_prompt = str(row.prompt or "")
    preflight = analyze_shot_risk(
        _shot_row_to_preflight_payload(row),
        project_goal=str((body or {}).get("project_goal") or ""),
    )
    rewritten_prompt = str(preflight.get("safe_prompt") or original_prompt).strip()
    if not rewritten_prompt or rewritten_prompt == original_prompt.strip():
        return {"ok": True, "shot_index": idx, "changed": False, "prompt": original_prompt, "director_preflight": preflight, "prompt_revision": None}

    revision = build_prompt_revision(
        shot_index=idx,
        original_prompt=original_prompt,
        rewritten_prompt=rewritten_prompt,
        source=REVISION_SOURCE_DIRECTOR_PREFLIGHT,
        preflight=preflight,
    )
    await _set_shot_prompt(db, project_id, user_id, idx, rewritten_prompt)
    saved = append_prompt_revision(project_id, revision)
    # 同步更新 workspace 文件——让大脑下次读取时识别到改写后的 prompt
    # 传入一个降级后的 preflight（risk_level=ready），阻断空模板分镜的重复判定
    waived_preflight = {**preflight, "risk_level": "ready", "risk_count": 0, "risks": [], "can_generate_image": True, "can_generate_video": True}
    await _sync_shot_to_workspace_file(project_id, idx, rewritten_prompt, waived_preflight)
    await db.commit()
    return {"ok": True, "shot_index": idx, "changed": True, "prompt": rewritten_prompt, "director_preflight": waived_preflight, "prompt_revision": saved}


@router.post("/{project_id}/shot-rows/{idx}/rollback-rewrite")
async def rollback_shot_safe_rewrite(
    project_id: str,
    idx: int,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    row = await _fetch_shot_row_for_revision(db, project_id, user_id, idx)
    revision = latest_prompt_revision(project_id, idx)
    requested_revision_id = str((body or {}).get("revision_id") or "").strip()
    if requested_revision_id and (not revision or revision.get("revision_id") != requested_revision_id):
        raise HTTPException(status_code=404, detail="Prompt revision not found or already rolled back")
    if not revision:
        raise HTTPException(status_code=404, detail="No prompt revision available to roll back")

    current_prompt = str(row.prompt or "")
    rewritten_prompt = str(revision.get("rewritten_prompt") or "")
    if current_prompt.strip() != rewritten_prompt.strip() and not bool((body or {}).get("force")):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "prompt_changed_after_rewrite",
                "message": "Current prompt no longer matches the rewritten prompt; pass force=true to roll back anyway.",
                "current_prompt": current_prompt,
                "rewritten_prompt": rewritten_prompt,
            },
        )

    original_prompt = str(revision.get("original_prompt") or "")
    await _set_shot_prompt(db, project_id, user_id, idx, original_prompt)
    rolled_back = mark_prompt_revision_rolled_back(project_id, idx, revision.get("revision_id"))
    await db.commit()
    return {
        "ok": True,
        "shot_index": idx,
        "prompt": original_prompt,
        "director_preflight": analyze_shot_risk({**_shot_row_to_preflight_payload(row), "prompt": original_prompt}),
        "prompt_revision": rolled_back,
    }


@router.get("/{project_id}/assets")
async def list_assets(
    project_id: str,
    asset_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    where = "WHERE project_id = :project_id AND user_id = :user_id AND status = 'active'"
    params: dict[str, Any] = {"project_id": project_id, "user_id": user_id}
    if asset_type:
        where += " AND asset_type = :asset_type"
        params["asset_type"] = asset_type

    result = await db.execute(
        text(
            f"""
            SELECT asset_id, asset_type, file_path, file_url, metadata_json, status, created_at, updated_at
            FROM assets
            {where}
            ORDER BY created_at DESC
            """
        ),
        params,
    )
    rows = result.fetchall()
    items = [_normalize_asset_row(r) for r in rows]
    return {"project_id": project_id, "items": items}


@router.get("/{project_id}/visual-plan")
async def get_visual_plan(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    _, _, plan = await _fetch_visual_plan_payload(db, project_id, user_id)
    return {"project_id": project_id, "planner_version": "preflight_actions_v1", **plan}


async def _apply_visual_plan_action_to_db(
    db: AsyncSession,
    project_id: str,
    user_id: int,
    action: dict[str, Any],
    *,
    requested_asset_id: str = "",
) -> dict[str, Any]:
    kind = str(action.get("kind") or "")
    column = REF_JSON_FIELDS.get(kind)
    shot_index = int(action.get("shot_index") or 0)
    if not column or shot_index <= 0:
        raise HTTPException(status_code=400, detail="Visual plan action cannot be applied")

    asset_id = str(requested_asset_id or "").strip()
    created_asset: dict[str, Any] | None = None
    if action.get("action_type") == "bind_existing":
        recommended = [str(item) for item in action.get("recommended_asset_ids") or []]
        asset_id = asset_id or (recommended[0] if recommended else "")
        if not asset_id or asset_id not in recommended:
            raise HTTPException(status_code=400, detail="A recommended asset_id is required")
    else:
        prompt_seed = str(action.get("prompt_seed") or action.get("description") or action.get("title") or "").strip()
        quality = analyze_production_text_effectiveness(prompt_seed, domain="reference_image")
        if not quality["ok"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Visual reference action is not actionable; concrete subject/scene/prop anchors are required.",
                    "action_id": action.get("id"),
                    "reasons": quality["reasons"],
                    "quality": quality,
                },
            )
        if not asset_id:
            asset_id = uuid.uuid4().hex[:16]
            metadata_json = build_planned_reference_metadata(action, asset_id=asset_id)
            await db.execute(
                text(
                    """
                    INSERT INTO assets (asset_id, project_id, user_id, asset_type, file_path, file_url, metadata_json)
                    VALUES (:asset_id, :project_id, :user_id, 'image', NULL, NULL, CAST(:metadata_json AS JSONB))
                    """
                ),
                {
                    "asset_id": asset_id,
                    "project_id": project_id,
                    "user_id": user_id,
                    "metadata_json": json.dumps(metadata_json, ensure_ascii=False),
                },
            )
            created_asset = {
                "asset_id": asset_id,
                "asset_type": "image",
                "file_url": None,
                "metadata_json": metadata_json,
                "status": "active",
            }

    row = await db.execute(
        text(
            f"""
            SELECT {column} AS refs
            FROM shot_rows
            WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :shot_index
            """
        ),
        {"project_id": project_id, "user_id": user_id, "shot_index": shot_index},
    )
    current_row = row.fetchone()
    if not current_row:
        raise HTTPException(status_code=404, detail="Shot row not found")
    current_refs = current_row.refs if isinstance(current_row.refs, list) else []
    next_refs = list(dict.fromkeys([*current_refs, asset_id]))
    await db.execute(
        text(
            f"""
            UPDATE shot_rows
            SET {column} = CAST(:refs AS JSONB), updated_at = NOW()
            WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :shot_index
            """
        ),
        {
            "project_id": project_id,
            "user_id": user_id,
            "shot_index": shot_index,
            "refs": json.dumps(next_refs, ensure_ascii=False),
        },
    )
    return {
        "ok": True,
        "project_id": project_id,
        "shot_index": shot_index,
        "action_id": action.get("id"),
        "asset_id": asset_id,
        "field": action.get("target_ref_field"),
        "refs": next_refs,
        "created_asset": created_asset,
    }


def _visual_reference_group_key(action: dict[str, Any]) -> str:
    kind = str(action.get("kind") or "").strip().lower()
    title = str(action.get("title") or "").strip().lower()
    prompt_seed = str(action.get("prompt_seed") or "").strip().lower()
    return f"{kind}:{title or prompt_seed[:80]}"


@router.post("/{project_id}/visual-plan/actions/{action_id}/apply")
async def apply_visual_plan_action(
    project_id: str,
    action_id: str,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)
    _, _, plan = await _fetch_visual_plan_payload(db, project_id, user_id)
    action = next((item for item in plan.get("asset_actions", []) if item.get("id") == action_id), None)
    if not action:
        raise HTTPException(status_code=404, detail="Visual plan action not found")

    result = await _apply_visual_plan_action_to_db(
        db,
        project_id,
        user_id,
        action,
        requested_asset_id=str((body or {}).get("asset_id") or ""),
    )
    await db.commit()
    return result


@router.get("/{project_id}/assets/{aid}")
async def get_asset(
    project_id: str,
    aid: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    result = await db.execute(
        text(
            """
            SELECT asset_id, asset_type, file_path, file_url, metadata_json, status, created_at, updated_at
            FROM assets
            WHERE asset_id = :aid AND project_id = :project_id AND user_id = :user_id AND status = 'active'
            """
        ),
        {"aid": aid, "project_id": project_id, "user_id": user_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Asset not found")
    return _normalize_asset_row(row)


@router.post("/{project_id}/assets")
async def create_asset(
    project_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    asset_id = uuid.uuid4().hex[:16]
    asset_type = body.get("asset_type", "image")
    file_path = body.get("file_path")
    file_url = body.get("file_url")
    metadata_json = default_lineage_metadata(
        _normalize_asset_metadata(body),
        asset_type=asset_type,
        fallback_kind="shot_keyframe" if asset_type == "image" else asset_type,
    )

    await db.execute(
        text(
            """
            INSERT INTO assets (asset_id, project_id, user_id, asset_type, file_path, file_url, metadata_json)
            VALUES (:asset_id, :project_id, :user_id, :asset_type, :file_path, :file_url, CAST(:metadata_json AS JSONB))
            """
        ),
        {
            "asset_id": asset_id,
            "project_id": project_id,
            "user_id": user_id,
            "asset_type": asset_type,
            "file_path": file_path,
            "file_url": file_url,
            "metadata_json": json.dumps(metadata_json or {}, ensure_ascii=False),
        },
    )
    await db.commit()
    return {"id": asset_id, "asset_id": asset_id, "asset_type": asset_type, "status": "active"}


@router.post("/{project_id}/assets/upload")
async def upload_asset_file(
    project_id: str,
    file: UploadFile = File(...),
    asset_type: str = Form("generic"),
    metadata_json: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    asset_id = uuid.uuid4().hex[:16]
    raw_metadata = _parse_json_object(metadata_json) or {}
    role = str(raw_metadata.get("role") or "").strip().lower()
    if role == "golden_reference":
        raw_metadata.setdefault("asset_kind", "golden_reference")
        raw_metadata.setdefault("entity_type", "golden_reference")
        raw_metadata.setdefault("lineage_role", "source")
    elif role == "source_video":
        raw_metadata.setdefault("asset_kind", "source_video")
        raw_metadata.setdefault("entity_type", "source_video")
        raw_metadata.setdefault("lineage_role", "source")
    parsed_metadata = default_lineage_metadata(
        raw_metadata,
        asset_type=asset_type,
        fallback_kind="shot_keyframe" if asset_type == "image" else asset_type,
    )
    content_type = file.content_type or "application/octet-stream"
    if asset_type == "audio":
        _validate_audio_asset(file.filename, content_type)
    ext = _guess_extension(file.filename, content_type)
    total_size = 0
    file_path: str | None = None
    file_url: str | None = None
    settings = get_settings()
    oss_enabled = bool(settings.oss_access_key and settings.oss_secret_key)

    try:
        uploaded_bytes = await file.read()
    finally:
        await file.close()
    total_size = len(uploaded_bytes)
    if total_size <= 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # OSS path (if configured) or local fallback.
    if oss_enabled:
        key = f"projects/{project_id}/assets/{uuid.uuid4().hex}{ext}"
        try:
            storage_service.client.upload_fileobj(
                BytesIO(uploaded_bytes),
                storage_service.bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )
            file_path = key
            file_url = storage_service.get_public_url(key)
        except Exception:
            abs_path, local_url = _build_local_asset_paths(project_id, ext)
            with abs_path.open("wb") as output:
                output.write(uploaded_bytes)
            file_path = str(abs_path)
            file_url = local_url
    else:
        abs_path, local_url = _build_local_asset_paths(project_id, ext)
        with abs_path.open("wb") as output:
            output.write(uploaded_bytes)
        file_path = str(abs_path)
        file_url = local_url

    merged_metadata = {
        **parsed_metadata,
        "filename": parsed_metadata.get("filename") or (file.filename or ""),
        "mime": parsed_metadata.get("mime") or content_type,
        "size": parsed_metadata.get("size") or total_size,
        "upload_mode": "stream",
    }

    await db.execute(
        text(
            """
            INSERT INTO assets (asset_id, project_id, user_id, asset_type, file_path, file_url, metadata_json)
            VALUES (:asset_id, :project_id, :user_id, :asset_type, :file_path, :file_url, CAST(:metadata_json AS JSONB))
            """
        ),
        {
            "asset_id": asset_id,
            "project_id": project_id,
            "user_id": user_id,
            "asset_type": asset_type,
            "file_path": file_path,
            "file_url": file_url,
            "metadata_json": json.dumps(merged_metadata, ensure_ascii=False),
        },
    )
    await db.commit()

    return {
        "id": asset_id,
        "asset_id": asset_id,
        "asset_type": asset_type,
        "file_url": file_url,
        "file_path": file_path,
        "metadata_json": merged_metadata,
        "status": "active",
    }


@router.post("/{project_id}/assets/import-url")
async def import_asset_from_url(
    project_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    await _ensure_project_owner(db, project_id, user_id)

    source_url = str((body or {}).get("url") or "").strip()
    asset_type = str((body or {}).get("asset_type") or "audio").strip() or "audio"
    filename = str((body or {}).get("filename") or "").strip()
    metadata = _normalize_asset_metadata(body) or {}
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    validate_public_media_url(source_url)
    if asset_type != "audio":
        raise HTTPException(status_code=400, detail="Only audio URL import is supported")

    guessed_name = filename or Path(parsed.path).name or f"bgm_{uuid.uuid4().hex}.mp3"
    ext = Path(guessed_name).suffix.lower()
    total_size = 0
    content_type = "application/octet-stream"
    abs_path: Path | None = None
    local_url = ""
    try:
        with httpx.Client(timeout=180, follow_redirects=True) as client:
            with client.stream("GET", source_url) as response:
                validate_public_media_url(str(response.url))
                response.raise_for_status()
                content_type = response.headers.get("content-type", content_type).split(";")[0].strip()
                if not ext:
                    ext = _guess_extension(guessed_name, content_type) or ".mp3"
                _validate_audio_asset(guessed_name if Path(guessed_name).suffix else f"file{ext}", content_type)
                abs_path, local_url = _build_local_asset_paths(project_id, ext)
                with abs_path.open("wb") as output:
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        total_size += len(chunk)
                        if total_size > MAX_IMPORTED_ASSET_BYTES:
                            raise HTTPException(status_code=400, detail="Audio file is larger than the 200MB import limit")
                        output.write(chunk)
    except HTTPException:
        if abs_path and abs_path.exists():
            abs_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        if abs_path and abs_path.exists():
            abs_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to import audio URL: {exc}") from exc

    if total_size <= 0 or not abs_path:
        raise HTTPException(status_code=400, detail="Imported audio file is empty")

    asset_id = uuid.uuid4().hex[:16]
    merged_metadata = {
        **metadata,
        "filename": filename or guessed_name,
        "mime": content_type,
        "size": total_size,
        "source_url": source_url,
        "upload_mode": "url_import",
    }
    await db.execute(
        text(
            """
            INSERT INTO assets (asset_id, project_id, user_id, asset_type, file_path, file_url, metadata_json)
            VALUES (:asset_id, :project_id, :user_id, :asset_type, :file_path, :file_url, CAST(:metadata_json AS JSONB))
            """
        ),
        {
            "asset_id": asset_id,
            "project_id": project_id,
            "user_id": user_id,
            "asset_type": "audio",
            "file_path": str(abs_path),
            "file_url": local_url,
            "metadata_json": json.dumps(merged_metadata, ensure_ascii=False),
        },
    )
    await db.commit()
    return {
        "id": asset_id,
        "asset_id": asset_id,
        "asset_type": "audio",
        "file_url": local_url,
        "file_path": str(abs_path),
        "metadata_json": merged_metadata,
        "status": "active",
    }


@router.put("/{project_id}/assets/{aid}")
async def update_asset(
    project_id: str,
    aid: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    allowed = {"asset_type", "file_path", "file_url", "metadata_json", "metadata"}
    updates = {k: v for k, v in (body or {}).items() if k in allowed}
    if "metadata" in updates and "metadata_json" not in updates:
        updates["metadata_json"] = updates.pop("metadata")
    if "metadata_json" in updates:
        updates["metadata_json"] = _parse_json_object(updates["metadata_json"])

    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    params = {**updates, "aid": aid, "project_id": project_id, "user_id": user_id}
    result = await db.execute(
        text(
            f"""
            UPDATE assets
            SET {set_clause}, updated_at = NOW()
            WHERE asset_id = :aid AND project_id = :project_id AND user_id = :user_id AND status = 'active'
            """
        ),
        params,
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Asset not found")
    await db.commit()
    return {"ok": True, "asset_id": aid}


@router.delete("/{project_id}/assets/{aid}")
async def delete_asset(
    project_id: str,
    aid: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    result = await db.execute(
        text(
            """
            UPDATE assets
            SET status = 'deleted', updated_at = NOW()
            WHERE asset_id = :aid AND project_id = :project_id AND user_id = :user_id AND status = 'active'
            """
        ),
        {"aid": aid, "project_id": project_id, "user_id": user_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Asset not found")
    await db.commit()
    return {"ok": True, "asset_id": aid, "status": "deleted"}


# 鈹€鈹€鈹€ 缁?D锛氬獟浣撴枃浠?& 鍦烘櫙 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


@router.get("/{project_id}/media")
async def list_media(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        text("SELECT id, file_name, file_path, file_size, duration_sec, width, height, fps, video_codec, audio_codec, has_audio, created_at FROM media_files WHERE project_id = :pid AND user_id = :uid ORDER BY created_at DESC"),
        {"pid": project_id, "uid": current_user["id"]},
    )
    rows = result.mappings().fetchall()
    return {"project_id": project_id, "items": [dict(r) for r in rows]}


@router.get("/{project_id}/media/{media_id}/scenes")
async def list_scenes(
    project_id: str,
    media_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        text("SELECT id, scene_index, start_sec, end_sec, preview_image_path, status FROM scenes WHERE media_file_id = :mid ORDER BY scene_index ASC"),
        {"mid": media_id},
    )
    rows = result.mappings().fetchall()
    return {"media_file_id": media_id, "items": [dict(r) for r in rows]}


@router.get("/{project_id}/media/{media_id}/transcript")
async def get_transcript(
    project_id: str,
    media_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        text("SELECT id, scene_id, speaker, start_sec, end_sec, text, confidence FROM transcripts WHERE media_file_id = :mid ORDER BY start_sec ASC"),
        {"mid": media_id},
    )
    rows = result.mappings().fetchall()
    return {"media_file_id": media_id, "items": [dict(r) for r in rows]}


@router.patch("/{project_id}/scenes/{scene_id}")
async def update_scene(
    project_id: str,
    scene_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    action = body.get("action", "keep")
    if action not in ("keep", "delete"):
        raise HTTPException(400, "action must be keep or delete")

    if action == "delete":
        result = await db.execute(
            text("UPDATE scenes SET status = 'deleted' WHERE id = :sid AND project_id = :pid"),
            {"sid": scene_id, "pid": project_id},
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Scene not found")
        await db.commit()
        return {"ok": True, "scene_id": scene_id, "status": "deleted"}

    return {"ok": True, "scene_id": scene_id, "status": "kept"}


@router.get("/{project_id}/reports/{report_type}")
async def get_project_report(
    project_id: str,
    report_type: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        text("SELECT id, report_type, content_json, content_markdown, created_at FROM reports WHERE project_id = :pid AND report_type = :rtype ORDER BY created_at DESC LIMIT 1"),
        {"pid": project_id, "rtype": report_type},
    )
    row = result.mappings().fetchone()
    if not row:
        raise HTTPException(404, "Report not found")
    return dict(row)
