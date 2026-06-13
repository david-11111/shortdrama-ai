from __future__ import annotations

import asyncio
import importlib
import inspect
import random
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

import redis.asyncio as aioredis
from redis import Redis as SyncRedis
from sqlalchemy import text

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.services.credits import credit_service
from app.services.error_policy import classify_exception

_DISPATCH_RECEIPT_PREFIX = "dispatch:"
_TASK_LOCK_PREFIX = "task_exec_lock:"


def _clear_dispatch_receipt(task_id: str) -> None:
    """Remove the dispatch receipt from broker Redis — the task is no longer
    awaiting execution (worker picked it up, or it completed/failed).
    Best-effort, non-blocking."""
    try:
        client = SyncRedis.from_url(
            get_settings().celery_broker_url, decode_responses=True
        )
        client.delete(f"{_DISPATCH_RECEIPT_PREFIX}{task_id}")
        client.connection_pool.disconnect()
    except Exception:
        pass


LOGGER = logging.getLogger(__name__)


def acquire_task_lock(task_id: str, ttl_seconds: int = 1800) -> bool:
    """Attempt to acquire an idempotency lock for a task in broker Redis.

    Returns False if another worker is already executing this task
    (the reconciler may have re-dispatched a message that was merely
    delayed). The caller should ACK and return immediately on False.

    Lock is auto-released after *ttl_seconds* (default 30 min — covers
    the typical WAN2.1/Seedance generation window).
    """
    try:
        client = SyncRedis.from_url(
            get_settings().celery_broker_url, decode_responses=True
        )
        acquired = client.set(
            f"{_TASK_LOCK_PREFIX}{task_id}", "1", nx=True, ex=ttl_seconds
        )
        client.connection_pool.disconnect()
        return bool(acquired)
    except Exception as exc:
        LOGGER.warning("Task lock acquisition failed for %s: %s", task_id, exc)
        return True  # lock failure → allow execution (fail-open)


def release_task_lock(task_id: str) -> None:
    """Release the idempotency lock."""
    try:
        client = SyncRedis.from_url(
            get_settings().celery_broker_url, decode_responses=True
        )
        client.delete(f"{_TASK_LOCK_PREFIX}{task_id}")
        client.connection_pool.disconnect()
    except Exception:
        pass


def get_task_snapshot(task_id: str) -> dict[str, Any] | None:
    try:
        return asyncio.run(_get_task_snapshot(task_id))
    except Exception as exc:
        LOGGER.warning("Unable to read task snapshot for %s: %s", task_id, exc)
        return None


def publish_progress(
    task_id: str,
    *,
    status: str,
    progress: int,
    stage_text: str,
    retry_count: int | None = None,
    celery_task_id: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "task_update",
        "task_id": task_id,
        "status": status,
        "progress": progress,
        "stage_text": stage_text,
    }
    if extra:
        payload.update(dict(extra))
    asyncio.run(_persist_and_publish(
        _persist_progress(
            task_id,
            status=status,
            progress=progress,
            stage_text=stage_text,
            retry_count=retry_count,
            celery_task_id=celery_task_id,
        ),
        task_id,
        payload,
    ))
    return payload


def publish_complete(task_id: str, result: Any, *, celery_task_id: str | None = None) -> dict[str, Any]:
    payload = {"type": "task_complete", "task_id": task_id, "result": result}
    try:
        from app.services.provider_costs import record_provider_usage

        record_provider_usage(task_id=task_id, result=result)
    except Exception as exc:
        LOGGER.warning("Provider usage recording failed for %s: %s", task_id, exc)
    asyncio.run(_persist_and_publish(
        _persist_complete(task_id, result=result, celery_task_id=celery_task_id),
        task_id,
        payload,
    ))
    try:
        send_completion_email(task_id)
    except Exception as exc:
        LOGGER.warning("Email notification dispatch failed for %s: %s", task_id, exc)
    # Trigger work queue drain — fire-and-forget, errors must not affect task completion
    try:
        from app.tasks.admin_tasks import process_work_queue
        process_work_queue.delay()
    except Exception:
        pass
    return payload


def publish_failed(
    task_id: str,
    error: Exception,
    *,
    retry_count: int,
    credits_refunded: int = 0,
    dead_letter: bool = False,
    celery_task_id: str | None = None,
    task_type: str = "",
    shot_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = "dead_letter" if dead_letter else "failed"
    decision = classify_exception(error)

    # Error reflection: analyze failure with DeepSeek when retrying
    reflection = None
    if retry_count > 0 and not dead_letter:
        try:
            from app.services.error_reflection import reflect_on_failure_sync
            reflection = reflect_on_failure_sync(
                task_id,
                task_type=task_type,
                error_message=str(error),
                error_category=decision.category.value,
                retry_count=retry_count,
                shot_context=shot_context,
            )
        except Exception:
            pass

    payload = {
        "type": "task_failed",
        "task_id": task_id,
        "status": status,
        "error": str(error),
        "error_category": decision.category.value,
        "error_reason": decision.reason,
        "retryable": decision.retryable,
        "credits_refunded": credits_refunded,
    }
    if reflection:
        payload["reflection"] = reflection.as_dict()

    asyncio.run(_persist_failed_and_publish(
        task_id,
        payload,
        error=str(error),
        retry_count=retry_count,
        status=status,
        celery_task_id=celery_task_id,
        dead_letter=dead_letter,
    ))
    return payload


def resolve_callable(module_name: str, candidate_names: tuple[str, ...]) -> Callable[..., Any]:
    module = importlib.import_module(module_name)
    for candidate_name in candidate_names:
        candidate = getattr(module, candidate_name, None)
        if callable(candidate):
            return candidate
    raise AttributeError(f"No callable from {candidate_names!r} found in module {module_name!r}.")


def invoke_callable(
    func: Callable[..., Any],
    payload: Mapping[str, Any],
    *,
    api_key: str,
    task_id: str,
    user_id: str,
) -> Any:
    signature = inspect.signature(func)
    kwargs: dict[str, Any] = {}
    accepts_var_kwargs = False

    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            accepts_var_kwargs = True
            continue
        if parameter.name == "payload":
            kwargs[parameter.name] = dict(payload)
        elif parameter.name == "api_key":
            kwargs[parameter.name] = api_key
        elif parameter.name == "task_id":
            kwargs[parameter.name] = task_id
        elif parameter.name == "user_id":
            kwargs[parameter.name] = user_id
        elif parameter.name in payload:
            kwargs[parameter.name] = payload[parameter.name]

    if accepts_var_kwargs:
        for key, value in payload.items():
            kwargs.setdefault(key, value)
        kwargs.setdefault("api_key", api_key)
        kwargs.setdefault("task_id", task_id)
        kwargs.setdefault("user_id", user_id)

    if kwargs:
        return func(**kwargs)

    positional_count = len(signature.parameters)
    if positional_count == 1:
        return func(dict(payload))
    if positional_count == 2:
        return func(api_key, dict(payload))
    if positional_count >= 3:
        return func(api_key, user_id, dict(payload))
    return func()


def is_retryable_exception(error: Exception) -> bool:
    return classify_exception(error).retryable


def reflect_before_retry(
    task_id: str,
    exc: Exception,
    *,
    retry_count: int,
    task_type: str = "",
    payload: dict[str, Any],
    shot_context: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Run error reflection BEFORE retrying to get intelligent adjustments.

    Returns (strategy, adjusted_payload):
      - strategy: "retry" | "skip_shot" | "human_review"
      - adjusted_payload: the payload to use for retry (may have modified params)

    If reflection fails or is disabled, returns ("retry", original_payload) — safe fallback.
    """
    settings = get_settings()
    if not getattr(settings, "llm_error_reflection_enabled", False):
        return "retry", payload
    if not settings.deepseek_api_key:
        return "retry", payload

    try:
        from app.services.error_reflection import reflect_on_failure_sync
        from app.services.error_policy import classify_exception as _classify

        decision = _classify(exc)
        reflection = reflect_on_failure_sync(
            task_id,
            task_type=task_type,
            error_message=str(exc),
            error_category=decision.category.value,
            retry_count=retry_count,
            shot_context=shot_context,
        )
        if not reflection:
            return "retry", payload

        strategy = reflection.retry_strategy
        if strategy not in ("immediate", "backoff", "skip_shot", "human_review"):
            strategy = "retry"
        elif strategy in ("immediate", "backoff"):
            strategy = "retry"

        # Apply adjusted_params to the payload for the retry
        adjusted = reflection.adjusted_params or {}
        if adjusted and strategy == "retry":
            merged_payload = {**payload}
            # Merge into shot_row if that's where params live
            shot_row = merged_payload.get("shot_row")
            if isinstance(shot_row, dict):
                for key, value in adjusted.items():
                    if key in ("prompt", "negative_prompt", "duration", "seed", "cfg_scale"):
                        shot_row[key] = value
                merged_payload["shot_row"] = shot_row
            # Also merge top-level payload keys
            for key in ("prompt", "negative_prompt", "provider", "duration"):
                if key in adjusted:
                    merged_payload[key] = adjusted[key]
            LOGGER.info(
                "reflect_before_retry: applying adjusted_params for task %s: %s",
                task_id, list(adjusted.keys()),
            )
            return strategy, merged_payload

        return strategy, payload
    except Exception:
        LOGGER.debug("reflect_before_retry failed (non-blocking)", exc_info=True)
        return "retry", payload


def build_retry_delay(retry_count: int, *, base: int = 10, ceiling: int = 300) -> int:
    delay = min(ceiling, base * (2 ** retry_count))
    jitter = random.randint(0, max(1, delay // 2))
    return min(ceiling, delay + jitter)


def build_backpressure_delay(retry_count: int) -> int:
    """Linear 15s growth with jitter for backpressure waits. Cap at 120s."""
    base_delay = 15 * (retry_count + 1)
    jitter = random.randint(0, 10)
    return min(120, base_delay + jitter)


def publish_task_agent_event(task_id: str, event_type: str, data: dict[str, Any] | None = None) -> None:
    """Persist and publish a canonical Agent Runtime event for a task.

    Missing run_id is allowed so legacy/director tasks can still be observed
    by project. All events use the same schema and Redis channel as the
    BrainRunner observer: project:{project_id}:events.
    """
    try:
        asyncio.run(_persist_and_publish_task_agent_event(task_id, event_type, data or {}))
    except Exception as exc:
        LOGGER.warning("agent_event dispatch failed for %s: %s", task_id, exc)


async def _persist_and_publish_task_agent_event(task_id: str, event_type: str, data: dict[str, Any]) -> None:
    context = await _get_task_agent_context(task_id)
    if not context or not context.get("project_id"):
        return

    event = _build_task_agent_event(task_id, event_type, data, context)
    persisted = await _persist_agent_event(event)
    event["id"] = persisted["id"]
    event["created_at"] = persisted["created_at"]
    await _publish_agent_event_to_channel(str(context["project_id"]), event)


async def _persist_agent_event(event: dict[str, Any]) -> dict[str, Any]:
    meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
    if "agent_event" not in meta:
        from app.services.agent_runtime import normalize_agent_event

        meta["agent_event"] = normalize_agent_event(
            source=event.get("source"),
            event_type=event.get("event_type"),
            title=event.get("title"),
            detail=event.get("detail"),
            meta=meta,
        )
        event["meta"] = meta
        event.update(meta["agent_event"])
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    """
                    INSERT INTO agent_events (
                        run_id, project_id, task_id, user_id, source,
                        event_type, phase, title, detail, status, progress, meta
                    )
                    VALUES (
                        CAST(:run_id AS UUID), :project_id, CAST(:task_id AS UUID), :user_id, :source,
                        :event_type, :phase, :title, :detail, :status, :progress, CAST(:meta AS JSONB)
                    )
                    RETURNING id, created_at
                    """
                ),
                {
                    "run_id": event.get("run_id"),
                    "project_id": event.get("project_id"),
                    "task_id": event.get("task_id"),
                    "user_id": event.get("user_id"),
                    "source": event.get("source"),
                    "event_type": event["event_type"],
                    "phase": event.get("phase"),
                    "title": event.get("title"),
                    "detail": event.get("detail"),
                    "status": event.get("status"),
                    "progress": event.get("progress"),
                    "meta": json.dumps(event.get("meta") or {}, ensure_ascii=False, default=str),
                },
            )
            row = result.fetchone()
            return {
                "id": str(row.id),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }


async def _publish_agent_event_to_channel(project_id: str, event: dict[str, Any]) -> None:
    channel = f"project:{project_id}:events"
    async with aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True) as client:
        await client.publish(channel, json.dumps(event, ensure_ascii=False, default=str))


def _build_task_agent_event(
    task_id: str,
    event_type: str,
    data: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    task_type = str(context.get("task_type") or "task")
    source = _agent_event_source(event_type, task_type, data)
    status = _agent_event_status(event_type, data)
    phase = _agent_event_phase(event_type, data, status)
    title = _agent_event_title(event_type, task_type, data)
    detail = _agent_event_detail(event_type, data)
    actor = _agent_event_actor(task_type, data)
    event_kind = _agent_event_kind(event_type)
    summary = _agent_event_summary(event_type, task_type, data)
    reason = _agent_event_reason(event_type, data)
    artifact_refs = _agent_event_artifact_refs(data)
    debug = {"raw": data} if data else {}
    meta = {"task_type": task_type, **data}
    from app.services.agent_runtime import normalize_agent_event

    meta["agent_event"] = normalize_agent_event(
        source=source,
        event_type=event_type,
        title=title,
        detail=detail,
        meta=meta,
        actor=actor,
        event_kind=event_kind,
        visibility="user" if event_type != "risk" else "expert",
        summary=summary,
        reason=reason,
        artifact_refs=artifact_refs,
        debug=debug,
    )
    return {
        "type": "execution_event",
        "id": None,
        "run_id": str(context["run_id"]) if context.get("run_id") else None,
        "project_id": str(context["project_id"]),
        "task_id": task_id,
        "step_id": None,
        "user_id": context.get("user_id"),
        "source": source,
        "event_type": event_type,
        "phase": phase,
        "title": title,
        "detail": detail,
        "status": status,
        "progress": data.get("progress"),
        "meta": meta,
        **meta["agent_event"],
        "created_at": None,
    }


def _agent_event_actor(task_type: str, data: dict[str, Any]) -> str:
    text_value = f"{data.get('tool') or ''} {data.get('provider') or ''} {task_type}".lower()
    for actor in ("deepseek", "doubao", "seedream", "seedance", "kling", "ffmpeg"):
        if actor in text_value:
            return actor
    if "image" in text_value:
        return "seedream"
    if "video" in text_value:
        return "seedance"
    if "script" in text_value or "director" in text_value:
        return "doubao"
    return "executor"


def _agent_event_kind(event_type: str) -> str:
    return {
        "trace": "narration",
        "risk": "guardrail",
        "writeback": "tool_result",
    }.get(event_type, event_type if event_type in {"tool_call", "tool_result", "artifact", "error"} else "narration")


def _agent_event_summary(event_type: str, task_type: str, data: dict[str, Any]) -> str:
    label = _provider_label(str(data.get("tool") or data.get("provider") or ""), task_type)
    if event_type == "tool_call":
        return f"{label} 开始处理"
    if event_type == "tool_result":
        return f"{label} 返回结果"
    if event_type == "artifact":
        return f"{label} 生成产物"
    if event_type == "writeback":
        return f"结果已写回 {data.get('field') or 'media'}"
    if event_type == "error":
        return f"{label} 失败"
    if event_type == "risk":
        return f"{label} 等待恢复"
    return f"{label} 更新进度"


def _agent_event_reason(event_type: str, data: dict[str, Any]) -> str:
    if data.get("reason"):
        return str(data.get("reason"))
    if event_type == "tool_call":
        return str(data.get("action") or "request provider execution")
    if event_type == "writeback":
        return "persist provider result for the next brain run"
    if event_type == "error":
        return str(data.get("error_reason") or data.get("error") or "task failed")
    return ""


def _agent_event_artifact_refs(data: dict[str, Any]) -> list[Any]:
    refs = []
    for key in ("url", "asset_url", "image_url", "video_url", "oss_url", "result_url"):
        value = data.get(key)
        if value:
            refs.append({"kind": key, "uri": value})
    return refs


def _agent_event_source(event_type: str, task_type: str, data: dict[str, Any]) -> str:
    if event_type == "writeback":
        return "ledger"
    if event_type == "artifact":
        return "provider"
    if data.get("tool") == "key_pool":
        return "worker"
    return _task_source(task_type)


def _agent_event_status(event_type: str, data: dict[str, Any]) -> str:
    if event_type in {"tool_result", "artifact", "writeback"}:
        return "done"
    if event_type == "error":
        return "failed" if not data.get("retryable") else "blocked"
    if event_type == "risk":
        return "blocked"
    return "running"


def _agent_event_phase(event_type: str, data: dict[str, Any], status: str) -> str:
    if event_type == "tool_call":
        action = str(data.get("action") or "requesting")
        return f"{data.get('tool') or 'tool'}_{action}"
    if event_type == "tool_result":
        return f"{data.get('tool') or 'tool'}_result"
    if event_type == "artifact":
        return f"{data.get('type') or 'artifact'}_ready"
    if event_type == "writeback":
        return f"writeback_{data.get('field') or 'field'}"
    if event_type == "risk":
        return str(data.get("reason") or "risk")
    if event_type == "error":
        return "retry_waiting" if data.get("retryable") else "failed"
    return status


def _agent_event_title(event_type: str, task_type: str, data: dict[str, Any]) -> str:
    tool = str(data.get("tool") or task_type)
    if event_type == "tool_call":
        return f"\u8c03\u7528\u5de5\u5177\uff1a{_provider_label(tool, task_type)}"
    if event_type == "tool_result":
        return f"\u5de5\u5177\u8fd4\u56de\uff1a{_provider_label(tool, task_type)}"
    if event_type == "artifact":
        return f"\u4ea7\u7269\u751f\u6210\uff1a{data.get('type') or task_type}"
    if event_type == "writeback":
        return f"\u5199\u56de\u5206\u955c\uff1a{data.get('field') or 'media'}"
    if event_type == "risk":
        return f"\u98ce\u9669\u7b49\u5f85\uff1a{data.get('reason') or 'risk'}"
    if event_type == "error":
        return f"{_provider_label(tool, task_type)} \u5931\u8d25"
    return f"{_provider_label(tool, task_type)} \u4e8b\u4ef6"


def _agent_event_detail(event_type: str, data: dict[str, Any]) -> str:
    if event_type == "tool_call":
        if data.get("prompt"):
            return f"prompt={data.get('prompt')}"
        return str(data.get("action") or "calling")
    if event_type == "tool_result":
        parts = []
        if data.get("url"):
            parts.append(f"url={data.get('url')}")
        if data.get("duration_ms") is not None:
            parts.append(f"duration_ms={data.get('duration_ms')}")
        if data.get("key_name"):
            parts.append(f"key={data.get('key_name')}")
        return "\uff1b".join(parts) or "tool returned"
    if event_type == "artifact":
        return f"type={data.get('type') or 'artifact'}\uff1bsize={data.get('size', 0)}\uff1bduration={data.get('duration', '')}"
    if event_type == "writeback":
        return f"shot_index={data.get('shot_index')}\uff1bfield={data.get('field')}"
    if event_type == "risk":
        return f"reason={data.get('reason')}\uff1battempt={data.get('attempt')}"
    if event_type == "error":
        return str(data.get("error") or "task failed")
    return json.dumps(data, ensure_ascii=False, default=str)[:500]


def maybe_charge(transaction_id: str | None) -> None:
    if transaction_id:
        asyncio.run(credit_service.charge(transaction_id))


def maybe_refund(transaction_id: str | None) -> int:
    if not transaction_id:
        return 0
    try:
        return asyncio.run(credit_service.refund(transaction_id))
    except Exception as exc:
        LOGGER.exception("Refund failed for transaction %s: %s", transaction_id, exc)
        return 0


async def _persist_and_publish(persist_coro, task_id: str, payload: dict[str, Any]) -> None:
    # Clear dispatch receipt on any status transition — task is no longer waiting for pickup
    _clear_dispatch_receipt(task_id)
    await persist_coro
    await _publish_async(task_id, payload)
    await _publish_agent_task_event(task_id, payload)
    if payload.get("type") in ("task_complete", "task_failed"):
        await _drain_pending_instruction(task_id)
        await _observe_run_coordination_after_task(task_id)
        chain_result = await _apply_main_chain_after_task(task_id)
        if _should_finalize_after_chain(chain_result):
            await _maybe_finalize_run(task_id)


async def _drain_pending_instruction(task_id: str) -> None:
    try:
        from app.services.agent_pending_instructions import drain_pending_instruction_after_task

        await drain_pending_instruction_after_task(task_id)
    except Exception as exc:
        LOGGER.warning("Pending instruction drain failed for %s: %s", task_id, exc)


async def _observe_run_coordination_after_task(task_id: str) -> None:
    try:
        from app.services.run_coordination import observe_task_terminal_decision_tick

        await observe_task_terminal_decision_tick(task_id)
    except Exception as exc:
        LOGGER.warning("Run coordination decision tick failed for %s: %s", task_id, exc)


async def _apply_main_chain_after_task(task_id: str) -> dict[str, Any] | None:
    try:
        from app.services.main_chain_terminal import continue_main_chain_after_task

        return await continue_main_chain_after_task(task_id)
    except Exception as exc:
        LOGGER.warning("Main chain continuation failed for %s: %s", task_id, exc)
        return {"status": "failed", "dispatched": False, "continuation_failed": True, "error": str(exc)}


def _should_finalize_after_chain(chain_result: dict[str, Any] | None) -> bool:
    if isinstance(chain_result, dict):
        if chain_result.get("dispatched") or chain_result.get("continuation_failed"):
            return False
    return True


async def _persist_failed_and_publish(
    task_id: str,
    payload: dict[str, Any],
    *,
    error: str,
    retry_count: int,
    status: str,
    celery_task_id: str | None,
    dead_letter: bool,
) -> None:
    await _persist_failed(task_id, error=error, retry_count=retry_count, status=status, celery_task_id=celery_task_id)
    if dead_letter:
        await _move_to_dead_letter(task_id, error=error)
    await _publish_async(task_id, payload)
    await _publish_agent_task_event(task_id, payload)
    await _drain_pending_instruction(task_id)
    await _observe_run_coordination_after_task(task_id)
    chain_result = await _apply_main_chain_after_task(task_id)
    if _should_finalize_after_chain(chain_result):
        await _maybe_finalize_run(task_id)


async def _publish_async(task_id: str, payload: dict[str, Any]) -> None:
    channel = f"task:{task_id}:progress"
    try:
        async with aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True) as client:
            await client.publish(channel, json.dumps(payload, ensure_ascii=False, default=str))
    except Exception as exc:
        LOGGER.warning("Redis publish failed for %s: %s", task_id, exc)


async def _publish_agent_task_event(task_id: str, payload: dict[str, Any]) -> None:
    try:
        context = await _get_task_agent_context(task_id)
        if not context or not context.get("project_id") or not context.get("run_id"):
            return
        from app.services.agent_runtime import normalize_task_agent_state, publish_project_event_sync

        event_type = {
            "task_update": "trace",
            "task_complete": "tool_result",
            "task_failed": "error",
        }.get(str(payload.get("type") or ""), "trace")
        status = normalize_task_agent_state(str(payload.get("status") or ""))
        if payload.get("type") == "task_complete":
            status = "done"
        if payload.get("type") == "task_failed":
            status = "failed"
        event = {
            "type": "execution_event",
            "id": f"task-{task_id}-{payload.get('type')}-{payload.get('progress', '')}",
            "run_id": str(context.get("run_id")),
            "project_id": str(context.get("project_id")),
            "task_id": task_id,
            "source": _task_source(str(context.get("task_type") or "")),
            "event_type": event_type,
            "phase": status,
            "title": _task_event_title(context, payload),
            "detail": str(payload.get("stage_text") or payload.get("error") or "Task updated"),
            "status": status,
            "progress": payload.get("progress"),
            "meta": {"task_type": context.get("task_type"), "raw": payload},
            "created_at": None,
        }
        from app.services.agent_runtime import normalize_agent_event

        event["meta"]["agent_event"] = normalize_agent_event(
            source=event["source"],
            event_type=event["event_type"],
            title=event["title"],
            detail=event["detail"],
            meta=event["meta"],
            actor=_agent_event_actor(str(context.get("task_type") or ""), payload.get("raw") if isinstance(payload.get("raw"), dict) else payload),
            event_kind=_agent_event_kind(event["event_type"]),
            summary=event["title"],
            reason=str(payload.get("stage_text") or payload.get("error") or ""),
            debug={"raw": payload},
        )
        event.update(event["meta"]["agent_event"])
        publish_project_event_sync(str(context["project_id"]), event)
    except Exception as exc:
        LOGGER.warning("Agent task event publish failed for %s: %s", task_id, exc)


async def _get_task_agent_context(task_id: str) -> dict[str, Any] | None:
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    """
                    SELECT task_id, project_id, run_id, task_type, user_id
                    FROM tasks
                    WHERE task_id = CAST(:task_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"task_id": task_id},
            )
            row = result.mappings().first()
            return dict(row) if row else None
    except Exception:
        return None


def _task_source(task_type: str) -> str:
    if "export" in task_type or "final" in task_type:
        return "ffmpeg"
    if "image" in task_type or "video" in task_type or "tts" in task_type:
        return "provider"
    return "worker"


def _task_event_title(context: dict[str, Any], payload: dict[str, Any]) -> str:
    task_type = str(context.get("task_type") or "task")
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    provider = _provider_label(str(raw.get("provider") or payload.get("provider") or ""), task_type)
    if payload.get("type") == "task_complete":
        return f"{provider} \u5b8c\u6210"
    if payload.get("type") == "task_failed":
        return f"{provider} \u5931\u8d25"
    progress = payload.get("progress")
    stage = str(payload.get("stage_text") or "").strip()
    if progress is not None and stage:
        return f"{provider} \u6267\u884c\u4e2d\uff1a{progress}% {stage}"
    return f"{provider} \u6267\u884c\u4e2d"


def _provider_label(tool: str, task_type: str = "") -> str:
    text_value = f"{tool} {task_type}".lower()
    if "kling" in text_value:
        return "Kling \u89c6\u9891"
    if "seedream" in text_value or "image" in text_value:
        return "Seedream \u51fa\u56fe"
    if "seedance" in text_value or "video" in text_value:
        return "Seedance \u89c6\u9891"
    if "doubao" in text_value or "script" in text_value or "director" in text_value:
        return "\u8c46\u5305\u5267\u672c/\u5bfc\u6f14"
    return tool or task_type or "\u5de5\u5177"


async def _get_task_snapshot(task_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT status, result, run_id::text AS run_id, project_id, task_type, payload
                FROM tasks
                WHERE task_id = CAST(:task_id AS uuid)
                LIMIT 1
                """
            ),
            {"task_id": task_id},
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None


async def _persist_progress(
    task_id: str,
    *,
    status: str,
    progress: int,
    stage_text: str,
    retry_count: int | None,
    celery_task_id: str | None,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE tasks
                        SET status = :status,
                            progress = :progress,
                            stage_text = :stage_text,
                            retry_count = COALESCE(:retry_count, retry_count),
                            celery_task_id = COALESCE(:celery_task_id, celery_task_id),
                            started_at = CASE
                                WHEN started_at IS NULL AND :status_check = 'running' THEN NOW()
                                ELSE started_at
                            END,
                            updated_at = NOW()
                        WHERE task_id = CAST(:task_id AS uuid)
                          AND status <> 'cancelled'
                        """
                    ),
                    {
                        "task_id": task_id,
                        "status": status,
                        "status_check": status,
                        "progress": progress,
                        "stage_text": stage_text,
                        "retry_count": retry_count,
                        "celery_task_id": celery_task_id,
                    },
                )
    except Exception as exc:
        LOGGER.warning("Task progress persistence failed for %s: %s", task_id, exc)


async def _persist_complete(task_id: str, *, result: Any, celery_task_id: str | None) -> None:
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE tasks
                        SET status = 'done',
                            progress = 100,
                            stage_text = 'Completed',
                            result = CAST(:result_json AS JSONB),
                            celery_task_id = COALESCE(:celery_task_id, celery_task_id),
                            completed_at = NOW(),
                            updated_at = NOW()
                        WHERE task_id = CAST(:task_id AS uuid)
                          AND status <> 'cancelled'
                        """
                    ),
                    {
                        "task_id": task_id,
                        "result_json": json.dumps(result, ensure_ascii=False, default=str),
                        "celery_task_id": celery_task_id,
                    },
                )
    except Exception as exc:
        LOGGER.warning("Task completion persistence failed for %s: %s", task_id, exc)


async def _maybe_finalize_run(task_id: str) -> None:
    """If all sibling tasks under the same run are terminal, mark the run completed."""
    try:
        async with AsyncSessionLocal() as session:
            row = (await session.execute(
                text("SELECT run_id FROM tasks WHERE task_id = CAST(:task_id AS uuid) AND run_id IS NOT NULL LIMIT 1"),
                {"task_id": task_id},
            )).mappings().first()
            if not row or not row["run_id"]:
                return
            run_id = str(row["run_id"])
            counts = (await session.execute(
                text("""
                    SELECT COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE status IN ('done','failed','cancelled','dead_letter')) AS terminal
                    FROM tasks WHERE run_id = CAST(:run_id AS UUID)
                """),
                {"run_id": run_id},
            )).mappings().first()
            if not counts or counts["total"] == 0 or counts["terminal"] < counts["total"]:
                return
            run_row = (await session.execute(
                text("SELECT status FROM agent_runs WHERE id = CAST(:run_id AS UUID) LIMIT 1"),
                {"run_id": run_id},
            )).mappings().first()
            if not run_row or run_row["status"] in ("completed", "failed", "cancelled"):
                return
            has_failure = counts["terminal"] > 0 and (await session.execute(
                text("SELECT 1 FROM tasks WHERE run_id = CAST(:run_id AS UUID) AND status IN ('failed','dead_letter') LIMIT 1"),
                {"run_id": run_id},
            )).scalar_one_or_none() is not None
            final_status = "failed" if has_failure else "completed"
            await session.execute(
                text("UPDATE agent_runs SET status = :status, ended_at = NOW(), updated_at = NOW() WHERE id = CAST(:run_id AS UUID)"),
                {"run_id": run_id, "status": final_status},
            )
            await session.commit()
    except Exception as exc:
        LOGGER.warning("Run finalization check failed for task %s: %s", task_id, exc)


async def _persist_failed(
    task_id: str,
    *,
    error: str,
    retry_count: int,
    status: str,
    celery_task_id: str | None,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE tasks
                        SET status = :status,
                            error_message = :error_message,
                            retry_count = :retry_count,
                            stage_text = 'Failed',
                            celery_task_id = COALESCE(:celery_task_id, celery_task_id),
                            completed_at = NOW(),
                            updated_at = NOW()
                        WHERE task_id = CAST(:task_id AS uuid)
                          AND status <> 'cancelled'
                        """
                    ),
                    {
                        "task_id": task_id,
                        "status": status,
                        "error_message": error,
                        "retry_count": retry_count,
                        "celery_task_id": celery_task_id,
                    },
                )
    except Exception as exc:
        LOGGER.warning("Task failure persistence failed for %s: %s", task_id, exc)


async def _move_to_dead_letter(task_id: str, *, error: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO dead_letter_tasks (
                            original_task_id,
                            user_id,
                            task_type,
                            payload,
                            error_history
                        )
                        SELECT
                            task_id,
                            user_id,
                            task_type,
                            payload,
                            CAST(:error_history AS JSONB)
                        FROM tasks
                        WHERE task_id = CAST(:task_id AS uuid)
                        """
                    ),
                    {
                        "task_id": task_id,
                        "error_history": json.dumps([{"error": error}], ensure_ascii=False),
                    },
                )
    except Exception as exc:
        LOGGER.warning("Dead-letter persistence failed for %s: %s", task_id, exc)


def send_completion_email(task_id: str) -> None:
    """
    Query the task's user email and result, then dispatch an email notification
    via Celery (non-blocking). Failures are silently swallowed.
    """
    try:
        from app.tasks.notification_tasks import send_email_task
        from app.services.email import email_service

        task_snapshot = asyncio.run(_get_task_email_info(task_id))
        if not task_snapshot:
            return

        user_email = task_snapshot.get("email")
        if not user_email:
            return

        task_type = task_snapshot.get("task_type", "task")
        result = task_snapshot.get("result") or {}
        result_url = result.get("url") if isinstance(result, dict) else None

        subject = f"Your {task_type} task is complete"
        html_body = email_service._render_task_complete(task_type, task_id, result_url)

        send_email_task.delay(user_email, subject, html_body)
    except Exception as exc:
        LOGGER.warning("send_completion_email failed for task %s: %s", task_id, exc)


async def _get_task_email_info(task_id: str) -> dict[str, Any] | None:
    """Fetch task type, result, and user email for notification."""
    try:
        async with AsyncSessionLocal() as session:
            row = await session.execute(
                text(
                    """
                    SELECT t.task_type, t.result, u.email
                    FROM tasks t
                    JOIN users u ON u.id = t.user_id
                    WHERE t.task_id = CAST(:task_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"task_id": task_id},
            )
            mapping = row.mappings().first()
            return dict(mapping) if mapping else None
    except Exception as exc:
        LOGGER.warning("_get_task_email_info failed for %s: %s", task_id, exc)
        return None


def persist_result_to_oss(result: dict[str, Any], task_type: str) -> dict[str, Any]:
    """
    将任务结果中的外部 URL 持久化到 OSS。
    返回更新后的 result（url 替换为 OSS URL）。
    """
    from app.services.storage import storage_service

    try:
        settings = get_settings()
        if not settings.oss_access_key:
            return result

        # 视频/图片：下载外部 URL 并上传到 OSS
        if result.get("url") and result["url"].startswith("http"):
            folder = f"results/{task_type}"
            uploaded = storage_service.upload_from_url(result["url"], folder=folder)
            result["original_url"] = result["url"]
            result["url"] = uploaded["url"]
            result["oss_key"] = uploaded["key"]
            result["file_size"] = uploaded["size"]

        # TTS 音频：base64 数据上传到 OSS
        if result.get("audio_base64"):
            import base64
            audio_data = base64.b64decode(result["audio_base64"])
            folder = f"results/{task_type}"
            key = storage_service.upload_bytes(
                audio_data,
                content_type="audio/mpeg",
                folder=folder,
            )
            result["url"] = storage_service.get_public_url(key)
            result["oss_key"] = key
            result["file_size"] = len(audio_data)
            del result["audio_base64"]

    except Exception as exc:
        LOGGER.warning("Failed to persist result to OSS: %s", exc)

    return result


def result_url(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return ""
    return str(result.get("url") or result.get("video_url") or result.get("image_url") or "")


async def update_shot_media(
    project_id: str,
    shot_index: int,
    user_id: str,
    *,
    image_url: str = "",
    video_url: str = "",
    image_candidate: dict[str, Any] | None = None,
    video_candidate: dict[str, Any] | None = None,
    status: str,
) -> None:
    if not project_id or not shot_index:
        return

    updates: dict[str, Any] = {"status": status, "last_error": None}
    if image_url:
        updates["selected_image"] = image_url
        updates["image_candidates_json"] = [image_candidate or image_url]
    if video_url:
        updates["selected_video"] = video_url
        updates["video_variants_json"] = [video_candidate or video_url]
    await _update_shot_row(project_id, shot_index, user_id, updates)


async def update_shot_error(
    project_id: str,
    shot_index: int,
    user_id: str,
    error: str,
    *,
    status: str = "error",
) -> None:
    if not project_id or not shot_index:
        return
    await _update_shot_row(
        project_id,
        shot_index,
        user_id,
        {"status": status, "last_error": error[:500]},
    )
    try:
        from app.services.project_workspace import write_project_workspace_file

        write_project_workspace_file(
            project_id,
            relative_path="memory/failures.md",
            content=(
                "\n## Media Task Failure\n\n"
                f"- shot_index: {shot_index}\n"
                f"- status: {status}\n"
                f"- error: {error[:500]}\n"
                "- source: media_task_writeback\n"
                "- reason: persist provider/task failure for next brain run\n"
            ),
            mode="append",
            source="media_task_writeback",
            reason="media task failed and updated shot_rows.last_error",
            name=project_id,
        )
    except Exception:
        LOGGER.exception("Failed to write project failure memory for %s #%s", project_id, shot_index)


async def _update_shot_row(
    project_id: str,
    shot_index: int,
    user_id: str,
    updates: dict[str, Any],
) -> None:
    user_pk = int(user_id) if str(user_id).isdigit() else 0
    assignments: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {
        "project_id": project_id,
        "user_id": user_pk,
        "shot_index": shot_index,
    }
    json_fields = {"image_candidates_json", "video_variants_json"}

    for field, value in updates.items():
        if field in json_fields:
            assignments.append(f"{field} = COALESCE({field}, '[]'::jsonb) || CAST(:{field} AS JSONB)")
            params[field] = json.dumps(value, ensure_ascii=False)
        else:
            assignments.append(f"{field} = :{field}")
            params[field] = value

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text(
                    f"""
                    UPDATE shot_rows
                    SET {", ".join(assignments)}
                    WHERE project_id = :project_id
                      AND user_id = :user_id
                      AND shot_index = :shot_index
                    """
                ),
                params,
            )
