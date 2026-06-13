from __future__ import annotations

import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

import anyio
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from app.config import get_settings


router = APIRouter(prefix="/media", tags=["media"])
LOCAL_LTX_DIR = Path("storage") / "ltx_downloads"


@router.get("/ltx/files/{file_id}")
async def proxy_ltx_file(file_id: str) -> Response:
    safe_file_id = file_id.strip()
    if not safe_file_id or any(ch in safe_file_id for ch in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail="Invalid file_id")

    settings = get_settings()
    base_url = str(
        getattr(settings, "ltx_api_base_url", "")
        or getattr(settings, "inference_api_base_url", "")
        or ""
    ).rstrip("/")
    api_key = str(
        getattr(settings, "ltx_api_key", "")
        or getattr(settings, "inference_api_key", "")
        or ""
    )
    if not base_url or not api_key:
        raise HTTPException(status_code=503, detail="LTX API is not configured")

    url = f"{base_url}/v1/files/{urllib.parse.quote(safe_file_id, safe='')}"
    try:
        content, content_type = await anyio.to_thread.run_sync(_download_ltx_file, url, api_key)
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail="LTX file download failed") from exc
    except OSError as exc:
        raise HTTPException(status_code=502, detail="LTX file download error") from exc

    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


def _download_ltx_file(url: str, api_key: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read(), resp.headers.get("content-type", "application/octet-stream")


@router.get("/local/ltx/{filename}")
async def local_ltx_file(filename: str) -> FileResponse:
    safe_filename = filename.strip()
    if (
        not safe_filename
        or any(ch in safe_filename for ch in ("/", "\\", ".."))
        or not safe_filename.lower().endswith((".mp4", ".webm", ".mov"))
    ):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = LOCAL_LTX_DIR / safe_filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Local LTX file not found")
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={"Cache-Control": "private, max-age=86400"},
    )
