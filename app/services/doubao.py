"""
豆包 (Doubao) 文本生成服务 — 火山引擎 Ark API。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services.usage_meter import doubao_usage

logger = logging.getLogger(__name__)


def _raise_ark_error(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip()
        if len(detail) > 500:
            detail = detail[:500]
        raise RuntimeError(
            f"Doubao request failed with status={response.status_code}: {detail or exc!s}"
        ) from exc


def generate_text(api_key: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    调用豆包 Chat Completion API 生成文本。
    """
    settings = get_settings()
    base_url = settings.ark_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    messages: list[dict[str, str]] = []
    if payload.get("system_prompt"):
        messages.append({"role": "system", "content": payload["system_prompt"]})
    messages.append({"role": "user", "content": payload.get("prompt", "")})

    request_body = {
        "model": settings.ark_text_model,
        "messages": messages,
        "temperature": payload.get("temperature", 0.7),
        "max_tokens": payload.get("max_tokens", 2048),
        "stream": False,
    }

    timeout_seconds = _coerce_request_timeout(
        payload.get("timeout_seconds", kwargs.get("timeout_seconds"))
    )
    timeout = httpx.Timeout(
        connect=min(30.0, timeout_seconds),
        read=timeout_seconds,
        write=min(30.0, timeout_seconds),
        pool=min(30.0, timeout_seconds),
    )
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=request_body,
        )
        _raise_ark_error(response)
        data = response.json()

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"Doubao returned no choices: {data}")

    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message") or {}
    content = message.get("content", "")
    if isinstance(content, list):
        content = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )

    usage = data.get("usage") or {}
    total_tokens = int(usage.get("total_tokens", 0) or 0)
    logger.info("Doubao generated %d tokens", total_tokens)

    return {
        "text": str(content),
        "tokens_used": total_tokens,
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "cached_tokens": int(
            usage.get("cached_tokens", usage.get("cached_token", usage.get("cache_hit_tokens", 0))) or 0
        ),
        "model": settings.ark_text_model,
        "billing_usage": doubao_usage(settings.ark_text_model, usage),
        "status": "completed",
    }


def _coerce_request_timeout(value: Any) -> float:
    if value is None:
        return 300.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 300.0
    return max(1.0, min(parsed, 300.0))


# ---------------------------------------------------------------------------
# Seedance prompt rendering (中文→英文执行稿)
# ---------------------------------------------------------------------------

_TRANSLATE_STRUCTURED_PROMPT = (
    "将以下中文视频画面描述翻译成结构化英文，保留 subject/action/camera/lighting/style 结构，只输出英文："
)

_SEEDANCE_RENDER_SYSTEM_PROMPT = (
    "You are a Seedance prompt engineer. "
    "Convert the Chinese director's draft below into a concise, executable English video prompt for Seedance. "
    "Rules:\n"
    "1. Output English only, no explanations.\n"
    "2. Structure: subject → appearance → action → camera → lighting → style → negative constraints.\n"
    "3. Use hard cinematic keywords: e.g. shallow DOF, rack focus, anamorphic lens flare, "
    "motivated key light, handheld drift, slow push-in, match cut.\n"
    "4. Keep it under 120 words. One paragraph.\n"
    "5. End with a negative constraint line starting with 'Negative:' listing things to avoid."
)


def translate_to_english(chinese_prompt: str) -> str:
    """把中文 prompt 翻译成结构化英文，保留 subject/action/camera/lighting/style 结构。"""
    settings = get_settings()
    api_key = getattr(settings, "ark_api_key", "") or ""
    if not api_key:
        return chinese_prompt
    try:
        result = generate_text(api_key, {
            "system_prompt": "",
            "prompt": f"{_TRANSLATE_STRUCTURED_PROMPT}{chinese_prompt}",
            "temperature": 0.3,
            "max_tokens": 512,
        })
        return result.get("text", "") or chinese_prompt
    except Exception:
        return chinese_prompt


def render_seedance_prompt_en(cn_prompt: str, *, return_meta: bool = False):
    """Render a Chinese director draft into an executable English Seedance prompt.

    Falls back to translate_to_english() if the API call fails.
    """
    def _result(prompt: str, strategy: str, error: str = ""):
        if return_meta:
            return {"prompt": prompt, "strategy": strategy, "error": error}
        return prompt

    settings = get_settings()
    api_key = getattr(settings, "ark_api_key", "") or ""
    if not api_key:
        return _result(translate_to_english(cn_prompt), "translate_fallback", "ark_api_key not set")

    try:
        result = generate_text(api_key, {
            "system_prompt": _SEEDANCE_RENDER_SYSTEM_PROMPT,
            "prompt": cn_prompt,
            "temperature": 0.4,
            "max_tokens": 512,
        })
        rendered = (result.get("text", "") or "").strip()
        if rendered:
            return _result(rendered, "render")
    except Exception as exc:
        return _result(translate_to_english(cn_prompt), "translate_fallback", str(exc))

    return _result(translate_to_english(cn_prompt), "translate_fallback", "empty_response")
