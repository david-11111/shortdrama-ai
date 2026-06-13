"""
Kling (可灵) 视频生成服务。

API 文档: https://docs.klingai.com
认证方式: API Key 或 Access Key + Secret Key (JWT)
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5
MAX_POLL_TIME = 600


def _normalize_duration(raw: Any, default: int = 5) -> int:
    if isinstance(raw, (int, float)):
        value = int(raw)
    elif isinstance(raw, str):
        text = raw.strip().lower()
        matched = re.match(r"^(\d+(?:\.\d+)?)\s*s?$", text)
        if not matched:
            logger.warning("Kling received invalid duration=%r, fallback to %s", raw, default)
            return default
        value = int(float(matched.group(1)))
    else:
        logger.warning("Kling received invalid duration=%r, fallback to %s", raw, default)
        return default

    if value <= 0:
        return default

    if value not in {5, 10}:
        # Kling stable durations are 5s/10s; keep request valid.
        mapped = 5 if value < 8 else 10
        logger.warning("Kling duration=%s is not supported, mapped to %s", value, mapped)
        return mapped

    return value


def _raise_kling_error(response: httpx.Response, stage: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip()[:500]
        raise RuntimeError(
            f"Kling {stage} failed with status={response.status_code}: {detail or exc!s}"
        ) from exc


def generate_video(api_key: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    调用 Kling API 生成视频。

    payload 期望字段:
      - prompt: str
      - duration: int (5/10)
      - mode: str ("std" / "pro")
      - image_url: str (可选，图生视频)
    """
    settings = get_settings()
    base_url = settings.kling_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    duration = _normalize_duration(payload.get("duration", 5))
    request_body = {
        "prompt": payload.get("prompt", ""),
        "duration": str(duration),
        "mode": payload.get("mode", "std"),
    }
    if payload.get("image_url"):
        request_body["image"] = payload["image_url"]
    if payload.get("resolution"):
        aspect_map = {"1080p": "16:9", "720p": "16:9", "square": "1:1"}
        request_body["aspect_ratio"] = aspect_map.get(payload["resolution"], "16:9")

    timeout = httpx.Timeout(connect=30.0, read=30.0, write=30.0, pool=30.0)
    with httpx.Client(timeout=timeout) as client:
        submit_resp = client.post(
            f"{base_url}/videos/generations",
            headers=headers,
            json=request_body,
        )
        _raise_kling_error(submit_resp, "submit")
        task_data = submit_resp.json()

        task_id = (
            task_data.get("data", {}).get("task_id")
            or task_data.get("task_id")
            or task_data.get("id")
        )
        if not task_id:
            raise RuntimeError(f"Kling submit response missing task_id: {task_data}")
        logger.info("Kling task submitted: %s", task_id)

        start_time = time.time()
        while time.time() - start_time < MAX_POLL_TIME:
            time.sleep(POLL_INTERVAL)
            poll_resp = client.get(
                f"{base_url}/videos/generations/{task_id}",
                headers=headers,
            )
            _raise_kling_error(poll_resp, f"poll task_id={task_id}")
            poll_data = poll_resp.json()

            data = poll_data.get("data", poll_data)
            status = str(data.get("task_status", data.get("status", ""))).lower()

            if status in {"succeed", "succeeded", "completed"}:
                result = data.get("task_result", data.get("result", data))
                videos = result.get("videos", [])
                if videos and isinstance(videos[0], dict):
                    video_url = videos[0].get("url", "")
                else:
                    video_url = result.get("video_url", result.get("url", ""))

                if not video_url:
                    raise RuntimeError(f"Kling completed without video url: {poll_data}")

                logger.info("Kling task completed: %s", task_id)
                return {
                    "url": video_url,
                    "duration": duration,
                    "task_id": task_id,
                    "status": "completed",
                    "provider": "kling",
                }

            if status in {"failed", "error", "cancelled"}:
                error_msg = data.get("task_status_msg", data.get("message", "Unknown error"))
                raise RuntimeError(f"Kling task {task_id} failed: {error_msg}")

            logger.debug("Kling polling task_id=%s status=%s", task_id, status)

    raise TimeoutError(f"Kling task {task_id} timed out after {MAX_POLL_TIME}s")
