"""
Seedream 图片生成服务 — 火山引擎 Ark API。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services.usage_meter import seedream_usage

logger = logging.getLogger(__name__)


def _raise_ark_error(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip()
        if len(detail) > 500:
            detail = detail[:500]
        raise RuntimeError(
            f"Seedream request failed with status={response.status_code}: {detail or exc!s}"
        ) from exc


def generate_image(api_key: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    调用 Seedream API 生成图片。
    """
    settings = get_settings()
    base_url = settings.ark_base_url.rstrip("/")
    width = payload.get("width", 2048)
    height = payload.get("height", 2048)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    request_body = {
        "model": settings.ark_image_model,
        "prompt": payload.get("prompt", ""),
        "size": f"{width}x{height}",
        "n": 1,
    }
    if payload.get("negative_prompt"):
        request_body["negative_prompt"] = payload["negative_prompt"]
    if payload.get("style"):
        request_body["style"] = payload["style"]

    timeout = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/images/generations",
            headers=headers,
            json=request_body,
        )
        _raise_ark_error(response)
        data = response.json()

    images = data.get("data") or []
    if not images:
        raise RuntimeError(f"Seedream returned no images: {data}")

    first_image = images[0] if isinstance(images[0], dict) else {}
    image_url = first_image.get("url") or first_image.get("image_url")
    if not image_url:
        raise RuntimeError(f"Seedream response missing image url: {data}")

    logger.info("Seedream image generated")
    return {
        "url": image_url,
        "width": width,
        "height": height,
        "model": settings.ark_image_model,
        "billing_usage": seedream_usage(
            model=settings.ark_image_model,
            payload=payload,
            response=data,
            image_count=len(images),
            width=int(width),
            height=int(height),
        ),
        "status": "completed",
    }
