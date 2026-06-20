"""FastAPI router for LTX Desktop lifecycle and media actions.

All endpoints are prefixed with ``/api/ltx-desktop``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.ltx_desktop import LtxDesktopService, LtxDesktopUnavailableError

LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/ltx-desktop", tags=["ltx-desktop"])


# ── request models ──────────────────────────────────────────

class OpenInDesktopRequest(BaseModel):
    media_url: str
    action: str = "preview"  # preview | edit | image-to-video | extract-conditioning
    prompt: str = ""


# ── helpers ─────────────────────────────────────────────────

def _get_service() -> LtxDesktopService:
    return LtxDesktopService()


def _extract_gpu_info(health: dict) -> dict | None:
    """Pull GPU info from the /health response."""
    try:
        gpu = health.get("gpu") or {}
        if gpu:
            return {
                "name": str(gpu.get("name", "")),
                "memory": str(gpu.get("memory", "")),
                "utilization": float(gpu.get("utilization", 0)),
            }
        # Fallback: parse from system_info
        sys_info = health.get("system_info") or {}
        return {
            "name": str(sys_info.get("gpu_name", "")),
            "memory": str(sys_info.get("vram", "")),
            "utilization": 0,
        }
    except Exception:
        return None


# ── endpoints ───────────────────────────────────────────────

@router.get("/health")
async def ltx_desktop_health():
    """Check whether the LTX Desktop backend is running."""
    service = _get_service()
    health = service.health()
    running = health.get("status") == "ok"
    return {
        "running": running,
        "gpu": _extract_gpu_info(health) if running else None,
        "uptime": health.get("uptime_seconds") if running else None,
    }


@router.post("/launch")
async def ltx_desktop_launch():
    """Manually start the LTX Desktop backend."""
    service = _get_service()
    started = service.ensure_running()
    if not started:
        raise HTTPException(status_code=503, detail="Failed to launch LTX Desktop backend")
    return {"status": "ok", "message": "LTX Desktop backend started"}


@router.post("/shutdown")
async def ltx_desktop_shutdown():
    """Gracefully stop the LTX Desktop backend."""
    service = _get_service()
    service.shutdown()
    return {"status": "ok", "message": "LTX Desktop backend stopped"}


@router.post("/open")
async def ltx_desktop_open(req: OpenInDesktopRequest):
    """Send a media file to LTX Desktop for preview or processing.

    * ``preview`` — return local file info
    * ``image-to-video`` — submit as image-to-video generation
    * ``extract-conditioning`` — extract IC-LoRA conditioning
    """
    service = _get_service()
    try:
        result = service.send_media(req.media_url, req.action, req.prompt)
        return result
    except LtxDesktopUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
