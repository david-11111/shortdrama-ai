from __future__ import annotations

from typing import Any


def _text_len(value: Any) -> int:
    return len(str(value or ""))


def _compact_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def doubao_usage(model: str, usage: dict[str, Any] | None) -> dict[str, Any]:
    usage = usage or {}
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    cached_tokens = int(
        usage.get("cached_tokens", usage.get("cached_token", usage.get("cache_hit_tokens", 0))) or 0
    )
    cache_storage_token_hours = int(
        usage.get("cache_storage_token_hours", usage.get("cached_token_hours", 0)) or 0
    )
    total_tokens = int(usage.get("total_tokens", 0) or 0)
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens + cached_tokens

    return {
        "provider": "volcengine",
        "service": "doubao",
        "model": model,
        "billing_basis": "text_tokens",
        "input": _compact_dict({
            "prompt_tokens": prompt_tokens,
            "cached_tokens": cached_tokens,
            "cache_storage_token_hours": cache_storage_token_hours,
        }),
        "output": _compact_dict({
            "completion_tokens": completion_tokens,
        }),
        "total": {
            "tokens": total_tokens,
        },
        "raw_usage": usage,
    }


def seedream_usage(
    *,
    model: str,
    payload: dict[str, Any],
    response: dict[str, Any] | None,
    image_count: int,
    width: int,
    height: int,
) -> dict[str, Any]:
    response = response or {}
    raw_usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    prompt = payload.get("prompt", "")
    negative_prompt = payload.get("negative_prompt", "")
    ref_images = payload.get("ref_images") or payload.get("image_urls") or []
    if isinstance(ref_images, str):
        ref_images = [ref_images]

    return {
        "provider": "volcengine",
        "service": "seedream",
        "model": model,
        "billing_basis": "image_generation",
        "input": _compact_dict({
            "prompt_chars": _text_len(prompt),
            "negative_prompt_chars": _text_len(negative_prompt),
            "reference_images": len(ref_images) if isinstance(ref_images, list) else 0,
            "raw_tokens": raw_usage.get("prompt_tokens"),
        }),
        "output": _compact_dict({
            "images": image_count,
            "width": width,
            "height": height,
            "pixels": width * height * image_count,
            "raw_tokens": raw_usage.get("completion_tokens"),
        }),
        "total": _compact_dict({
            "raw_tokens": raw_usage.get("total_tokens"),
        }),
        "raw_usage": raw_usage,
    }


def seedance_usage(
    *,
    model: str,
    payload: dict[str, Any],
    submit_response: dict[str, Any] | None,
    poll_response: dict[str, Any] | None,
    duration: int,
    resolution: str,
    aspect_ratio: str,
) -> dict[str, Any]:
    submit_response = submit_response or {}
    poll_response = poll_response or {}
    raw_usage = {}
    for source in (submit_response, poll_response):
        usage = source.get("usage")
        if isinstance(usage, dict):
            raw_usage.update(usage)

    prompt = payload.get("prompt", "")
    has_image = bool(payload.get("image_url"))

    return {
        "provider": "volcengine",
        "service": "seedance",
        "model": model,
        "billing_basis": "video_generation",
        "input": _compact_dict({
            "prompt_chars": _text_len(prompt),
            "reference_images": 1 if has_image else 0,
            "raw_tokens": raw_usage.get("prompt_tokens"),
        }),
        "output": _compact_dict({
            "videos": 1,
            "duration_seconds": duration,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "raw_tokens": raw_usage.get("completion_tokens"),
        }),
        "total": _compact_dict({
            "raw_tokens": raw_usage.get("total_tokens"),
        }),
        "raw_usage": raw_usage,
    }
