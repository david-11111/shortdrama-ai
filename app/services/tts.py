"""
火山引擎 TTS 语音合成服务。

使用 Ark API 的语音合成端点。
"""
from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services.voice_delivery_rules import prepare_tts_payload

logger = logging.getLogger(__name__)


def _raise_tts_error(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip()[:500]
        raise RuntimeError(
            f"TTS request failed with status={response.status_code}: {detail or exc!s}"
        ) from exc


def generate_speech(api_key: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    调用火山引擎 TTS API 生成语音。

    payload 期望字段:
      - text: str
      - voice: str
      - speed: float
      - volume: float
    """
    settings = get_settings()
    payload = prepare_tts_payload(payload)
    base_url = settings.ark_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    text = payload.get("text", "")
    if not text:
        raise ValueError("TTS text cannot be empty")
    if len(text) > 5000:
        raise ValueError(f"TTS text too long: {len(text)} chars (max 5000)")

    request_body = {
        "model": settings.ark_tts_model,
        "input": text,
        "voice": payload.get("voice", "zh_female_shuangkuai"),
        "response_format": "mp3",
        "speed": payload.get("speed", 1.0),
    }
    if payload.get("volume") is not None:
        request_body["volume"] = payload["volume"]

    timeout = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/audio/speech",
            headers=headers,
            json=request_body,
        )
        _raise_tts_error(response)

        content_type = response.headers.get("content-type", "")
        if "audio" in content_type or "octet-stream" in content_type:
            audio_b64 = base64.b64encode(response.content).decode()
            duration_estimate = len(text) * 0.3
            logger.info("TTS generated audio: %d bytes", len(response.content))
            return {
                "audio_base64": audio_b64,
                "format": "mp3",
                "duration": duration_estimate,
                "characters": len(text),
                "status": "completed",
            }

        data = response.json()
        audio_url = data.get("url") or data.get("audio_url") or ""
        duration = data.get("duration", len(text) * 0.3)
        logger.info("TTS generated response via JSON")
        return {
            "url": audio_url,
            "format": "mp3",
            "duration": duration,
            "characters": len(text),
            "status": "completed",
        }
