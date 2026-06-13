"""Streaming LLM reply via DeepSeek, publishing token chunks to Redis."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

import httpx
import redis.asyncio as aioredis

from app.config import get_settings
from app.services.credits import credit_service

logger = logging.getLogger(__name__)

CHUNK_BATCH_INTERVAL = 0.05  # 50ms
CHUNK_BATCH_SIZE = 5  # tokens


async def _publish_to_redis(project_id: str, payload: dict[str, Any]) -> None:
    """Publish directly to Redis PubSub channel for the project."""
    try:
        settings = get_settings()
        client = aioredis.Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            channel = f"project:{project_id}:events"
            data = json.dumps(payload, ensure_ascii=False, default=str)
            await client.publish(channel, data)
        finally:
            await client.aclose()
    except Exception as exc:
        logger.error("llm_stream: Redis publish failed: %s", exc)


async def publish_llm_stream_event(
    project_id: str,
    *,
    event_type: str,
    stream_id: str,
    run_id: str,
    actor: str = "deepseek",
    content: str = "",
    index: int = 0,
    full_text: str = "",
    phase: str = "",
) -> None:
    payload = {
        "type": event_type,
        "stream_id": stream_id,
        "run_id": run_id,
        "actor": actor,
        "content": content,
        "index": index,
        "full_text": full_text,
        "phase": phase,
    }
    await _publish_to_redis(project_id, payload)


async def publish_planner_thinking(
    *,
    project_id: str,
    run_id: str,
    decision: dict[str, Any],
) -> None:
    """Publish planner reasoning as a single structured thinking event.

    Deliberately does NOT emit llm_think_start/chunk/end stream events —
    those interfere with the frontend's main reply stream rendering.
    All Redis errors are silently swallowed.
    """
    try:
        audit_rationale = str(decision.get("decision_rationale") or "").strip()
        audit_root_cause = str(decision.get("root_cause_layer") or "").strip()
        if not audit_rationale and not audit_root_cause:
            return

        event_payload = {
            "type": "thinking",
            "run_id": run_id,
            "actor": "deepseek",
            "phase": "planner_reasoning",
            "action": str(decision.get("action") or ""),
            "decision_rationale": audit_rationale,
            "root_cause_layer": audit_root_cause,
            "evidence_refs": decision.get("evidence_refs") or [],
            "confidence": decision.get("confidence"),
            "source": "planner_audit",
        }

        settings = get_settings()
        client = aioredis.Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            channel = f"project:{project_id}:events"
            await client.publish(channel, json.dumps(event_payload, ensure_ascii=False, default=str))
        finally:
            await client.aclose()
    except Exception:
        pass  # Thinking visibility must never break production


async def stream_pregenerated_reply(
    *,
    project_id: str,
    run_id: str,
    text: str,
    actor: str = "deepseek",
    phase: str = "human_response",
    chunk_size: int = 4,
    delay: float = 0.03,
) -> None:
    """Stream an already-generated reply text to the frontend in chunks."""
    if not text:
        logger.warning("stream_pregenerated_reply: empty text, skipping")
        return

    logger.info("stream_pregenerated_reply: starting for run=%s len=%d", run_id, len(text))
    stream_id = str(uuid.uuid4())

    await publish_llm_stream_event(
        project_id,
        event_type="llm_stream_start",
        stream_id=stream_id,
        run_id=run_id,
        actor=actor,
        phase=phase,
    )

    index = 0
    pos = 0
    while pos < len(text):
        chunk = text[pos:pos + chunk_size]
        await publish_llm_stream_event(
            project_id,
            event_type="llm_chunk",
            stream_id=stream_id,
            run_id=run_id,
            actor=actor,
            content=chunk,
            index=index,
            phase=phase,
        )
        pos += chunk_size
        index += 1
        await asyncio.sleep(delay)

    await publish_llm_stream_event(
        project_id,
        event_type="llm_stream_end",
        stream_id=stream_id,
        run_id=run_id,
        actor=actor,
        full_text=text,
        phase=phase,
    )
    logger.info("stream_pregenerated_reply: done, %d chunks", index)


async def stream_llm_reply_to_redis(
    *,
    project_id: str,
    run_id: str,
    system_prompt: str,
    user_content: str,
    actor: str = "deepseek",
    phase: str = "human_response",
    db: Any = None,
    user_id: int | None = None,
) -> str:
    """Call DeepSeek with stream=True and publish token chunks to Redis."""
    settings = get_settings()
    if not settings.deepseek_api_key:
        return ""

    stream_id = str(uuid.uuid4())

    await publish_llm_stream_event(
        project_id,
        event_type="llm_stream_start",
        stream_id=stream_id,
        run_id=run_id,
        actor=actor,
        phase=phase,
    )

    request_body = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
        "max_tokens": 800,
        "stream": True,
    }

    full_text = ""
    chunk_index = 0
    buffer = ""
    last_flush = time.monotonic()
    last_usage_token_count = 0

    try:
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    # Capture token usage from the final streaming chunk
                    usage_info = data.get("usage")
                    if usage_info:
                        last_usage_token_count = usage_info.get("total_tokens", 0) or 0
                    delta = (
                        ((data.get("choices") or [{}])[0].get("delta") or {})
                        .get("content") or ""
                    )
                    if not delta:
                        continue

                    full_text += delta
                    buffer += delta

                    now = time.monotonic()
                    if len(buffer) >= CHUNK_BATCH_SIZE or (now - last_flush) >= CHUNK_BATCH_INTERVAL:
                        await publish_llm_stream_event(
                            project_id,
                            event_type="llm_chunk",
                            stream_id=stream_id,
                            run_id=run_id,
                            actor=actor,
                            content=buffer,
                            index=chunk_index,
                            phase=phase,
                        )
                        chunk_index += 1
                        buffer = ""
                        last_flush = now
                        await asyncio.sleep(0)

        if buffer:
            await publish_llm_stream_event(
                project_id,
                event_type="llm_chunk",
                stream_id=stream_id,
                run_id=run_id,
                actor=actor,
                content=buffer,
                index=chunk_index,
                phase=phase,
            )

    except Exception as exc:
        logger.error("LLM stream failed: %s", exc)

    await publish_llm_stream_event(
        project_id,
        event_type="llm_stream_end",
        stream_id=stream_id,
        run_id=run_id,
        actor=actor,
        full_text=full_text,
        phase=phase,
    )

    if db and full_text:
        try:
            from app.services.agent_runtime import publish_agent_event
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                source="brain",
                event_type="tool_result",
                phase="human_response",
                title="DeepSeek \u56de\u590d",
                detail=full_text,
                status="done",
                actor=actor,
                event_kind="narration",
                visibility="user",
                user_id=user_id,
            )
        except Exception:
            pass

    # Charge LLM token usage (non-blocking)
    if user_id is not None and last_usage_token_count > 0:
        try:
            await credit_service.charge_direct(
                user_id=user_id,
                operation="llm_planner_call",
                token_count=last_usage_token_count,
                ref_id=f"llm:stream:{run_id}:{phase}",
            )
        except Exception:
            logger.warning("Failed to charge LLM tokens (non-blocking)", exc_info=True)

    return full_text
