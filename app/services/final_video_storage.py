from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.media_proxy import blob_streaming_response, proxy_remote_media_response


FINAL_VIDEO_DIR = Path("storage") / "final_videos"
FINAL_VIDEO_CONTENT_TYPE = "video/mp4"


def _safe_segment(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in str(value or ""))
    return safe.strip("._") or "unknown"


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def object_storage_asset(
    *,
    file_url: str,
    oss_key: str | None,
    file_size: int,
    content_type: str = FINAL_VIDEO_CONTENT_TYPE,
) -> dict[str, Any]:
    return {
        "storage_mode": "oss",
        "file_path": None,
        "file_url": file_url,
        "oss_key": oss_key,
        "file_size": int(file_size or 0),
        "checksum_sha256": None,
        "content_type": content_type,
    }


def copy_final_video_to_local_store(*, source_path: str, project_id: str, task_id: str) -> dict[str, Any]:
    target_dir = FINAL_VIDEO_DIR / _safe_segment(project_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{_safe_segment(task_id)}.mp4"
    shutil.copyfile(source_path, target)
    file_size = target.stat().st_size
    return {
        "storage_mode": "local_file",
        "file_path": str(target),
        "file_url": f"/api/director/final-video/{task_id}",
        "oss_key": None,
        "file_size": file_size,
        "checksum_sha256": _sha256_file(target),
        "content_type": FINAL_VIDEO_CONTENT_TYPE,
    }


async def upsert_final_video_asset(
    db: AsyncSession,
    *,
    task_id: str,
    project_id: str,
    user_id: int,
    asset: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO final_video_assets (
                task_id, project_id, user_id, storage_mode, content_type,
                file_size, file_path, file_url, oss_key, checksum_sha256, metadata_json
            )
            VALUES (
                CAST(:task_id AS UUID), :project_id, :user_id, :storage_mode, :content_type,
                :file_size, :file_path, :file_url, :oss_key, :checksum_sha256, CAST(:metadata_json AS JSONB)
            )
            ON CONFLICT (task_id)
            DO UPDATE SET
                project_id = EXCLUDED.project_id,
                user_id = EXCLUDED.user_id,
                storage_mode = EXCLUDED.storage_mode,
                content_type = EXCLUDED.content_type,
                file_size = EXCLUDED.file_size,
                file_path = EXCLUDED.file_path,
                file_url = EXCLUDED.file_url,
                oss_key = EXCLUDED.oss_key,
                checksum_sha256 = EXCLUDED.checksum_sha256,
                metadata_json = EXCLUDED.metadata_json,
                updated_at = NOW()
            """
        ),
        {
            "task_id": task_id,
            "project_id": project_id,
            "user_id": user_id,
            "storage_mode": str(asset.get("storage_mode") or ""),
            "content_type": str(asset.get("content_type") or FINAL_VIDEO_CONTENT_TYPE),
            "file_size": int(asset.get("file_size") or 0),
            "file_path": asset.get("file_path"),
            "file_url": asset.get("file_url"),
            "oss_key": asset.get("oss_key"),
            "checksum_sha256": asset.get("checksum_sha256"),
            "metadata_json": json.dumps(metadata or {}, ensure_ascii=False, default=str),
        },
    )


async def final_video_response(db: AsyncSession, *, task_id: str, user_id: int) -> Response:
    asset_result = await db.execute(
        text(
            """
            SELECT storage_mode, content_type, file_size, file_path, file_url
            FROM final_video_assets
            WHERE task_id = CAST(:task_id AS UUID) AND user_id = :user_id
            """
        ),
        {"task_id": task_id, "user_id": user_id},
    )
    asset = asset_result.mappings().first()
    if asset:
        mode = str(asset["storage_mode"] or "")
        if mode == "local_file":
            path = Path(str(asset["file_path"] or ""))
            if path.exists() and path.is_file():
                return FileResponse(
                    path,
                    media_type=asset["content_type"] or FINAL_VIDEO_CONTENT_TYPE,
                    headers={
                        "Content-Disposition": f'inline; filename="final-{task_id}.mp4"',
                        "Content-Length": str(int(asset["file_size"] or path.stat().st_size)),
                        "Cache-Control": "private, max-age=3600",
                    },
                )
            raise HTTPException(status_code=502, detail="Final video asset file is missing")
        if mode == "oss":
            url = str(asset["file_url"] or "")
            if url:
                return await proxy_remote_media_response(task_id, {"url": url, "model": "final_video"})
            raise HTTPException(status_code=502, detail="Final video asset URL is missing")
        if mode != "db_blob":
            raise HTTPException(status_code=502, detail=f"Unsupported final video storage mode: {mode}")

    blob_result = await db.execute(
        text(
            """
            SELECT content_type, file_size, data
            FROM final_video_blobs
            WHERE task_id = CAST(:task_id AS UUID) AND user_id = :user_id
            """
        ),
        {"task_id": task_id, "user_id": user_id},
    )
    blob = blob_result.fetchone()
    if not blob:
        raise HTTPException(status_code=404, detail="Final video not found")
    return blob_streaming_response(
        task_id=task_id,
        data=blob.data,
        content_type=blob.content_type,
        file_size=int(blob.file_size),
    )
