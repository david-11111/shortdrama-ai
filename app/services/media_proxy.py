from __future__ import annotations

import hashlib
import ipaddress
import socket
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse


MEDIA_PROXY_MAX_BYTES = 500 * 1024 * 1024
MEDIA_PROXY_CHUNK_SIZE = 1024 * 1024
CACHE_DIR = Path(tempfile.gettempdir()) / "shortdrama_media_cache"
ALLOWED_MEDIA_SCHEMES = {"http", "https"}


def extract_media_url(task_result: dict[str, Any]) -> str:
    return str(task_result.get("url") or task_result.get("video_url") or task_result.get("image_url") or "").strip()


def infer_media_type(task_result: dict[str, Any], url: str) -> tuple[str, str]:
    lowered = url.lower()
    is_video = "video" in str(task_result.get("model", "")).lower() or bool(task_result.get("duration")) or ".mp4" in lowered
    if is_video:
        return ".mp4", "video/mp4"
    if any(ext in lowered for ext in (".png", ".webp")):
        ext = ".webp" if ".webp" in lowered else ".png"
        return ext, f"image/{ext[1:]}"
    return ".jpg", "image/jpeg"


async def proxy_remote_media_response(task_id: str, task_result: dict[str, Any]) -> FileResponse:
    url = extract_media_url(task_result)
    if not url:
        raise HTTPException(status_code=404, detail="No media URL in task result")
    validate_public_media_url(url)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ext, content_type = infer_media_type(task_result, url)
    cache_key = hashlib.md5(f"{task_id}:{url[:100]}".encode()).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}{ext}"

    if cache_file.exists() and cache_file.stat().st_size > 0:
        file_size = cache_file.stat().st_size
    else:
        file_size = await _download_to_cache(url, cache_file)

    headers = {
        "Content-Disposition": f'inline; filename="{task_id}{ext}"',
        "Content-Length": str(file_size),
        "Cache-Control": "private, max-age=86400",
    }
    return FileResponse(cache_file, media_type=content_type, headers=headers)


def blob_streaming_response(
    *,
    task_id: str,
    data: Any,
    content_type: str,
    file_size: int,
) -> StreamingResponse:
    view = memoryview(data)

    def iter_blob():
        for offset in range(0, len(view), MEDIA_PROXY_CHUNK_SIZE):
            yield view[offset: offset + MEDIA_PROXY_CHUNK_SIZE].tobytes()

    headers = {
        "Content-Disposition": f'inline; filename="final-{task_id}.mp4"',
        "Content-Length": str(file_size),
        "Cache-Control": "private, max-age=3600",
    }
    return StreamingResponse(iter_blob(), media_type=content_type, headers=headers)


async def _download_to_cache(url: str, cache_file: Path) -> int:
    validate_public_media_url(url)
    temp_file = cache_file.with_suffix(cache_file.suffix + ".part")
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                validate_public_media_url(str(resp.url))
                if resp.status_code != 200:
                    raise HTTPException(status_code=502, detail=f"Failed to fetch media: HTTP {resp.status_code}")
                total = 0
                with temp_file.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(MEDIA_PROXY_CHUNK_SIZE):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MEDIA_PROXY_MAX_BYTES:
                            raise HTTPException(status_code=413, detail="Media file is too large to proxy")
                        fh.write(chunk)
        temp_file.replace(cache_file)
        return total
    except Exception:
        temp_file.unlink(missing_ok=True)
        cache_file.unlink(missing_ok=True)
        raise


def validate_public_media_url(url: str) -> None:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() not in ALLOWED_MEDIA_SCHEMES:
        raise HTTPException(status_code=400, detail="Media URL scheme is not allowed")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Media URL host is required")
    host = parsed.hostname.strip().rstrip(".")
    if not host:
        raise HTTPException(status_code=400, detail="Media URL host is required")
    if host.lower() in {"localhost", "localhost.localdomain"}:
        raise HTTPException(status_code=400, detail="Media URL host is not allowed")
    try:
        ip = ipaddress.ip_address(host)
        _reject_private_ip(ip)
        return
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="Media URL host cannot be resolved") from exc
    resolved_ips = {item[4][0] for item in infos if item and item[4]}
    if not resolved_ips:
        raise HTTPException(status_code=400, detail="Media URL host cannot be resolved")
    for value in resolved_ips:
        _reject_private_ip(ipaddress.ip_address(value))


def _reject_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise HTTPException(status_code=400, detail="Media URL resolves to a non-public address")
