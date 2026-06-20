from __future__ import annotations

import random
import time
from typing import Any

from app.celery_app import celery_app
from app.services.error_policy import classify_exception
from app.services.key_pool import BackpressureError, key_pool
from app.services.post_generation_review import media_candidate, review_image_candidate
from app.services.provider_prompt_adapter import adapt_provider_payload
from app.services.production_entrypoint import assert_agent_run_entrypoint_for_task
from app.services.ref_resolver import build_image_generation_payload
from app.tasks._shared import (
    acquire_task_lock,
    build_backpressure_delay,
    build_retry_delay,
    get_task_snapshot,
    invoke_callable,
    is_retryable_exception,
    maybe_charge,
    maybe_refund,
    persist_result_to_oss,
    publish_complete,
    publish_failed,
    publish_progress,
    publish_task_agent_event,
    reflect_before_retry,
    release_task_lock,
    result_url,
    resolve_callable,
    update_shot_error,
    update_shot_media,
)

MAX_RETRIES = 3
MAX_BACKPRESSURE_RETRIES = 8
BACKPRESSURE_INTERNAL_ATTEMPTS = 3
BACKPRESSURE_POLL_INTERVAL = 10


@celery_app.task(bind=True, queue="image", soft_time_limit=300, time_limit=600, acks_late=True)
def generate_image_task(
    self,
    task_id: str,
    user_id: str,
    payload: dict[str, Any],
    transaction_id: str | None = None,
) -> Any:
    snapshot = get_task_snapshot(task_id)
    if snapshot and snapshot.get("status") == "cancelled":
        return {"status": "cancelled", "task_id": task_id}
    if snapshot and snapshot.get("status") == "done" and snapshot.get("result") is not None:
        return snapshot["result"]

    # Idempotency lock: prevent duplicate execution from reconciled messages
    locked_this_run = False
    if acquire_task_lock(task_id):
        locked_this_run = True
    else:
        return {"status": "duplicate", "task_id": task_id}

    publish_progress(
        task_id,
        status="running",
        progress=5,
        stage_text="Preparing image task",
        retry_count=self.request.retries,
        celery_task_id=self.request.id,
    )
    key_name: str | None = None

    try:
        assert_agent_run_entrypoint_for_task(
            "image_gen",
            payload,
            db_run_id=str((snapshot or {}).get("run_id") or "").strip() or None,
        )
        shot_row_data = payload.get("shot_row")
        if shot_row_data:
            resolved = build_image_generation_payload(shot_row_data, strict=False)
            if resolved.get("subject_reference"):
                payload.setdefault("ref_images", []).extend(resolved["subject_reference"])
            if resolved.get("scene_reference"):
                payload.setdefault("scene_refs", []).extend(resolved["scene_reference"])
            if resolved.get("style_reference"):
                payload.setdefault("style_refs", []).extend(resolved["style_reference"])
            if resolved.get("prompt"):
                payload["prompt"] = resolved["prompt"]
        payload = adapt_provider_payload(payload, task_type="image_gen", provider=str(payload.get("provider") or "seedream"))

        key_name, api_key = None, None
        publish_task_agent_event(task_id, "tool_call", {"tool": "seedream", "action": "acquire_key"})
        for _bp_attempt in range(BACKPRESSURE_INTERNAL_ATTEMPTS):
            try:
                key_name, api_key = key_pool.acquire("seedream")
                break
            except BackpressureError:
                if _bp_attempt < BACKPRESSURE_INTERNAL_ATTEMPTS - 1:
                    publish_task_agent_event(task_id, "risk", {"reason": "backpressure", "attempt": _bp_attempt + 1})
                    publish_progress(
                        task_id,
                        status="running",
                        progress=10,
                        stage_text=f"Waiting for slot ({_bp_attempt + 1}/{BACKPRESSURE_INTERNAL_ATTEMPTS})",
                        retry_count=self.request.retries,
                        celery_task_id=self.request.id,
                    )
                    time.sleep(BACKPRESSURE_POLL_INTERVAL + random.randint(0, 5))
                else:
                    raise
        publish_task_agent_event(task_id, "tool_result", {"tool": "key_pool", "key_name": key_name})
        publish_progress(
            task_id,
            status="running",
            progress=15,
            stage_text="Calling Seedream",
            retry_count=self.request.retries,
            celery_task_id=self.request.id,
        )
        call = resolve_callable(
            "app.services.seedream",
            ("generate_image", "call_seedream", "submit_image_generation", "generate"),
        )
        publish_task_agent_event(task_id, "tool_call", {"tool": "seedream", "prompt": str(payload.get("prompt", ""))[:50]})
        _t0 = time.time()
        result = invoke_callable(call, payload, api_key=api_key, task_id=task_id, user_id=user_id)
        publish_task_agent_event(task_id, "tool_result", {
            "tool": "seedream", "url": str(result.get("url", ""))[:120], "duration_ms": int((time.time() - _t0) * 1000),
        })
        result = persist_result_to_oss(result, "image")
        if shot_row_data:
            import asyncio
            url = result_url(result)
            review = review_image_candidate(shot_row_data, url)

            asyncio.run(update_shot_media(
                str(shot_row_data.get("project_id") or ""),
                int(shot_row_data.get("shot_index") or 0),
                user_id,
                image_url=url,
                image_candidate=media_candidate(url, review),
                status="image_done",
            ))
            publish_task_agent_event(task_id, "writeback", {
                "shot_index": shot_row_data.get("shot_index"), "field": "selected_image",
            })
        maybe_charge(transaction_id)
        publish_progress(
            task_id,
            status="running",
            progress=100,
            stage_text="Image generation complete",
            retry_count=self.request.retries,
            celery_task_id=self.request.id,
        )
        publish_complete(task_id, result, celery_task_id=self.request.id)
        return result
    except Exception as exc:
        is_backpressure = isinstance(exc, BackpressureError)
        error_decision = classify_exception(exc)
        retryable = is_backpressure or error_decision.retryable
        publish_task_agent_event(task_id, "error", {
            "error": str(exc)[:200],
            "category": error_decision.category.value,
            "retryable": retryable,
            "retry_count": self.request.retries,
        })

        if key_name and error_decision.report_to_key_pool and not is_backpressure:
            key_pool.report_error(key_name, str(exc))

        max_retries = MAX_BACKPRESSURE_RETRIES if is_backpressure else MAX_RETRIES

        if retryable and self.request.retries < max_retries:
            if is_backpressure:
                delay = build_backpressure_delay(self.request.retries)
                publish_progress(
                    task_id,
                    status="retrying",
                    progress=15,
                    stage_text=f"Retrying image task ({self.request.retries + 1}/{max_retries})",
                    retry_count=self.request.retries + 1,
                    celery_task_id=self.request.id,
                )
                raise self.retry(exc=exc, countdown=delay)
            else:
                # Reflect on failure before retrying — may adjust payload or skip
                strategy, adjusted_payload = reflect_before_retry(
                    task_id, exc,
                    retry_count=self.request.retries,
                    task_type="image_gen",
                    payload=payload,
                    shot_context=payload.get("shot_row"),
                )
                if strategy == "skip_shot":
                    retryable = False
                else:
                    delay = build_retry_delay(self.request.retries)
                    publish_progress(
                        task_id,
                        status="retrying",
                        progress=15,
                        stage_text=f"Retrying image task ({self.request.retries + 1}/{max_retries})",
                        retry_count=self.request.retries + 1,
                        celery_task_id=self.request.id,
                    )
                    raise self.retry(
                        exc=exc,
                        countdown=delay,
                        args=(task_id, user_id, adjusted_payload, transaction_id),
                    )

        refunded = maybe_refund(transaction_id)
        shot_row_data = payload.get("shot_row")
        if shot_row_data:
            import asyncio

            error_text = str(exc)
            asyncio.run(update_shot_error(
                str(shot_row_data.get("project_id") or ""),
                int(shot_row_data.get("shot_index") or 0),
                user_id,
                error_text,
                status="image_done" if shot_row_data.get("selected_image") else "error",
            ))
        publish_failed(
            task_id,
            exc,
            retry_count=self.request.retries,
            credits_refunded=refunded,
            dead_letter=error_decision.dead_letter or is_backpressure,
            celery_task_id=self.request.id,
        )
        raise
    finally:
        if key_name:
            key_pool.release(key_name)
        if locked_this_run:
            release_task_lock(task_id)
