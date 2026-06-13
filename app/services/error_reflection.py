from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ErrorReflection:
    root_cause: str
    adjusted_params: dict[str, Any]
    retry_strategy: str  # "immediate" | "backoff" | "skip_shot" | "human_review"
    rationale: str
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "root_cause": self.root_cause,
            "adjusted_params": self.adjusted_params,
            "retry_strategy": self.retry_strategy,
            "rationale": self.rationale,
            "confidence": self.confidence,
        }


async def reflect_on_failure(
    task_id: str,
    task_type: str = "",
    error_message: str = "",
    error_category: str = "",
    retry_count: int = 0,
    shot_context: dict[str, Any] | None = None,
    error_history: list[dict[str, Any]] | None = None,
) -> ErrorReflection | None:
    """Analyze a task failure using DeepSeek and suggest corrective action.

    Returns None if LLM is unavailable or the analysis fails — caller should
    fall back to existing blind retry.
    """
    settings = get_settings()
    if not getattr(settings, "llm_error_reflection_enabled", False):
        return None
    if not settings.deepseek_api_key:
        return None

    try:
        return await _call_deepseek_reflection(
            settings,
            task_id=task_id,
            task_type=task_type,
            error_message=error_message,
            error_category=error_category,
            retry_count=retry_count,
            shot_context=shot_context,
            error_history=error_history,
        )
    except Exception as exc:
        logger.warning("Error reflection failed, falling back to blind retry: %s", exc)
        return None


async def _call_deepseek_reflection(
    settings: Any,
    *,
    task_id: str,
    task_type: str,
    error_message: str,
    error_category: str,
    retry_count: int,
    shot_context: dict[str, Any] | None,
    error_history: list[dict[str, Any]] | None,
) -> ErrorReflection | None:
    history_text = ""
    if error_history:
        for i, entry in enumerate(error_history, 1):
            history_text += f"  Attempt {i}: {entry.get('error', 'unknown')}\n"

    shot_text = ""
    if shot_context:
        shot_text = json.dumps(shot_context, ensure_ascii=False, default=str)[:2000]

    user_content = (
        f"Task: {task_type}\n"
        f"Error category: {error_category}\n"
        f"Error message: {error_message[:500]}\n"
        f"Retry count (current): {retry_count}\n"
        f"Error history:\n{history_text}\n"
        f"Shot context:\n{shot_text}"
    )

    system_prompt = (
        "You are the error root-cause analyzer for an AI short-drama production system. "
        "Given a failed task, diagnose WHY it failed and suggest a correction strategy. "
        "Output JSON with: root_cause (concise Chinese diagnostic), "
        "retry_strategy (one of: immediate | backoff | skip_shot | human_review), "
        "adjusted_params (object with fields to change e.g. prompt_suffix, temperature, max_duration, "
        "ref_image_count, remove_image — empty if no adjustment needed), "
        "rationale (Chinese sentence explaining the adjustment), confidence (0.0-1.0). "
        "Return JSON only."
    )

    request_body = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
        "stream": False,
        "response_format": {"type": "json_object"},
    }

    timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        response.raise_for_status()

    data = response.json()
    raw = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None

    retry_strategy = str(parsed.get("retry_strategy") or "backoff").strip().lower()
    if retry_strategy not in {"immediate", "backoff", "skip_shot", "human_review"}:
        retry_strategy = "backoff"

    adjusted = parsed.get("adjusted_params")
    if not isinstance(adjusted, dict):
        adjusted = {}

    confidence = 0.0
    try:
        confidence = float(parsed.get("confidence", 0))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        pass

    return ErrorReflection(
        root_cause=str(parsed.get("root_cause") or "").strip(),
        adjusted_params=adjusted,
        retry_strategy=retry_strategy,
        rationale=str(parsed.get("rationale") or "").strip(),
        confidence=confidence,
    )


def reflect_on_failure_sync(
    task_id: str,
    *,
    task_type: str = "",
    error_message: str = "",
    error_category: str = "",
    retry_count: int = 0,
    shot_context: dict[str, Any] | None = None,
    error_history: list[dict[str, Any]] | None = None,
) -> ErrorReflection | None:
    """Synchronous wrapper for Celery task context."""
    import asyncio
    try:
        return asyncio.run(reflect_on_failure(
            task_id=task_id,
            task_type=task_type,
            error_message=error_message,
            error_category=error_category,
            retry_count=retry_count,
            shot_context=shot_context,
            error_history=error_history,
        ))
    except Exception:
        return None
