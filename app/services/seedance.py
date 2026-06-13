"""
Seedance 视频生成服务 — 火山引擎 Ark API。
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from app.config import get_settings
from app.services.usage_meter import seedance_usage

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5
MAX_POLL_TIME = 1200


class PolicyViolationError(RuntimeError):
    """Raised when Seedance rejects a task due to policy/copyright violation."""

    def __init__(self, task_id: str, error_code: str, message: str) -> None:
        super().__init__(f"Seedance PolicyViolation task={task_id} code={error_code}: {message}")
        self.task_id = task_id
        self.error_code = error_code
        self.raw_message = message


_POLICY_SENSITIVE_PATTERNS = re.compile(
    r"\b(TVC|commercial\s+ad|advertising\s+film|brand\s+film|cinematic\s+commercial"
    r"|luxury\s+brand|product\s+advertisement|TV\s+commercial|ad\s+film"
    r"|promotional\s+video|marketing\s+video)\b",
    re.IGNORECASE,
)

_STYLE_TAG_PATTERN = re.compile(
    r"(奢华产品广告风格|电影级商业片|高端品牌影片|luxury\s+product\s+ad\s+style"
    r"|cinematic\s+commercial\s+film|high.end\s+brand\s+film)",
    re.IGNORECASE,
)


def _normalize_duration(raw: Any, default: int = 5) -> int:
    if isinstance(raw, (int, float)):
        value = int(raw)
        return value if value > 0 else default

    if isinstance(raw, str):
        text = raw.strip().lower()
        matched = re.match(r"^(\d+(?:\.\d+)?)\s*s?$", text)
        if matched:
            value = int(float(matched.group(1)))
            return value if value > 0 else default

    logger.warning("Seedance received invalid duration=%r, fallback to %s", raw, default)
    return default


def sanitize_prompt(prompt: str) -> str:
    """Remove or soften terms likely to trigger Seedance policy checks.

    Preserves subject, action, camera, and lighting descriptions.
    """
    result = _POLICY_SENSITIVE_PATTERNS.sub("cinematic short film", prompt)
    result = _STYLE_TAG_PATTERN.sub("cinematic style", result)
    result = re.sub(r"  +", " ", result).strip()
    return result


def _is_policy_violation(error_code: str, message: str) -> bool:
    combined = f"{error_code} {message}"
    return "PolicyViolation" in combined or "SensitiveContentDetected" in combined


def _raise_ark_error(service: str, response: httpx.Response, stage: str, task_id: str = "") -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip()
        if len(detail) > 500:
            detail = detail[:500]
        # Detect PolicyViolation in HTTP error body before raising generic error
        if _is_policy_violation(str(response.status_code), detail):
            raise PolicyViolationError(task_id or "submit", str(response.status_code), detail) from exc
        raise RuntimeError(
            f"{service} {stage} failed with status={response.status_code}: {detail or exc!s}"
        ) from exc


def _extract_task_id(task_data: dict[str, Any]) -> str:
    for key in ("id", "task_id"):
        value = task_data.get(key)
        if value:
            return str(value)
    raise RuntimeError(f"Seedance submit response missing task id: {task_data}")


def _extract_video_url(poll_data: dict[str, Any]) -> str:
    output = poll_data.get("output") or {}
    content = poll_data.get("content") or {}
    candidates = (
        content.get("video_url"),
        content.get("url"),
        output.get("video_url"),
        output.get("url"),
        poll_data.get("video_url"),
        poll_data.get("url"),
    )
    for candidate in candidates:
        if candidate:
            return str(candidate)

    data = poll_data.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                for key in ("video_url", "url"):
                    value = item.get(key)
                    if value:
                        return str(value)

    raise RuntimeError(f"Seedance completed without video url: {poll_data}")


def generate_video(api_key: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    调用 Seedance API 生成视频（Ark contents/generations/tasks 接口）。

    payload 期望字段:
      - prompt: str
      - duration: int
      - resolution: str
      - aspect_ratio: str (e.g. "16:9")
      - image_url: str (可选，首帧图)
    """
    settings = get_settings()
    base_url = settings.ark_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    duration = _normalize_duration(payload.get("duration", 5))
    resolution = str(payload.get("resolution", "1080p"))
    aspect_ratio = str(payload.get("aspect_ratio") or "16:9")
    base_prompt = str(payload.get("prompt", "")).strip()
    annotated_prompt = (
        f"{base_prompt} --resolution {resolution} --duration {duration} --ratio {aspect_ratio}"
    ).strip()

    content: list[dict[str, Any]] = [{"type": "text", "text": annotated_prompt}]
    if payload.get("image_url"):
        content.append({"type": "image_url", "image_url": {"url": payload["image_url"]}})

    request_body = {"model": settings.ark_video_model, "content": content}

    timeout = httpx.Timeout(connect=30.0, read=30.0, write=30.0, pool=30.0)
    with httpx.Client(timeout=timeout) as client:
        submit_resp = client.post(
            f"{base_url}/contents/generations/tasks",
            headers=headers,
            json=request_body,
        )
        _raise_ark_error("Seedance", submit_resp, "submit", task_id="submit")
        task_data = submit_resp.json()
        task_id = _extract_task_id(task_data)
        logger.info("Seedance task submitted: %s", task_id)

        start_time = time.time()
        while time.time() - start_time < MAX_POLL_TIME:
            time.sleep(POLL_INTERVAL)
            poll_resp = client.get(
                f"{base_url}/contents/generations/tasks/{task_id}",
                headers=headers,
            )
            _raise_ark_error("Seedance", poll_resp, f"poll task_id={task_id}", task_id=task_id)
            poll_data = poll_resp.json()
            status = str(poll_data.get("status", "")).lower()

            if status in {"succeeded", "completed"}:
                video_url = _extract_video_url(poll_data)
                logger.info("Seedance task completed: %s", task_id)
                return {
                    "url": video_url,
                    "duration": duration,
                    "task_id": task_id,
                    "model": settings.ark_video_model,
                    "billing_usage": seedance_usage(
                        model=settings.ark_video_model,
                        payload=payload,
                        submit_response=task_data,
                        poll_response=poll_data,
                        duration=duration,
                        resolution=resolution,
                        aspect_ratio=aspect_ratio,
                    ),
                    "status": "completed",
                }

            if status in {"failed", "error", "cancelled"}:
                error_data = poll_data.get("error") or {}
                error_code = str(
                    error_data.get("code") or error_data.get("err_code") or status
                )
                error_message = (
                    error_data.get("message")
                    or poll_data.get("message")
                    or poll_data.get("error_message")
                    or "Unknown error"
                )
                if _is_policy_violation(error_code, error_message):
                    raise PolicyViolationError(task_id, error_code, error_message)
                raise RuntimeError(
                    f"Seedance task {task_id} failed with status={status}: {error_message}"
                )

            logger.debug("Seedance polling task_id=%s status=%s", task_id, status)

    raise TimeoutError(f"Seedance task {task_id} timed out after {MAX_POLL_TIME}s")
