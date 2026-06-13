from __future__ import annotations

import time
from typing import Any

from app.celery_app import celery_app
from app.services.key_pool import key_pool
from app.services.post_generation_review import media_candidate, review_video_candidate
from app.services.provider_prompt_adapter import adapt_provider_payload
from app.services.production_entrypoint import assert_agent_run_entrypoint_for_task
from app.services.ref_resolver import build_video_generation_payload
from app.services.seedance import PolicyViolationError, sanitize_prompt
from app.services.error_policy import classify_exception
from app.tasks._shared import (
    acquire_task_lock,
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


@celery_app.task(bind=True, queue="video", soft_time_limit=1500, time_limit=1800, acks_late=True)
def generate_video_task(
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

    try:
        publish_progress(
            task_id,
            status="running",
            progress=5,
            stage_text="Preparing video task",
            retry_count=self.request.retries,
            celery_task_id=self.request.id,
        )
        key_name: str | None = None

        try:
            assert_agent_run_entrypoint_for_task(
                "video_gen",
                payload,
                db_run_id=str((snapshot or {}).get("run_id") or "").strip() or None,
            )
            shot_row_data = payload.get("shot_row")
            if shot_row_data:
                if shot_row_data.get("image_url") and not shot_row_data.get("selected_image"):
                    shot_row_data["selected_image"] = shot_row_data["image_url"]
                resolved = build_video_generation_payload(shot_row_data, strict=False)
                if resolved.get("prompt"):
                    payload["prompt"] = resolved["prompt"]
                if resolved.get("duration"):
                    payload["duration"] = resolved["duration"]
                if resolved.get("image") and not payload.get("image_url"):
                    payload["image_url"] = resolved["image"]
                if resolved.get("subject_reference"):
                    payload.setdefault("ref_images", []).extend(resolved["subject_reference"])

            provider = str(payload.get("provider", "ltx2.3")).lower()
            payload = adapt_provider_payload(payload, task_type="video_gen", provider=provider)

            # ── ComfyUI 本地视频生成（LTX / Wan2.1，不走 key_pool）──
            comfy_providers = {"ltx2.3", "ltx", "wan", "wan2.1", "wan2_1", "comfyui"}
            if provider in comfy_providers:
                from app.services.comfy_video import generate_comfy_video

                publish_task_agent_event(task_id, "tool_call", {"tool": provider, "action": "comfyui_submit"})
                publish_progress(
                    task_id, status="running", progress=15,
                    stage_text=f"Calling ComfyUI ({provider})",
                    retry_count=self.request.retries,
                    celery_task_id=self.request.id,
                )
                result = generate_comfy_video(payload, provider=provider)
                publish_task_agent_event(task_id, "tool_result", {
                    "tool": provider, "url": str(result.get("url", ""))[:120],
                })
                # ComfyUI 不走 key_pool，直接写回 + 完成
                shot_row_data = payload.get("shot_row")
                if shot_row_data:
                    url = result_url(result)
                    review = review_video_candidate(shot_row_data, url)
                    import asyncio
                    asyncio.run(update_shot_media(
                        str(shot_row_data.get("project_id") or ""),
                        int(shot_row_data.get("shot_index") or 0),
                        user_id,
                        video_url=url,
                        video_candidate=media_candidate(url, review),
                        status="video_done",
                    ))
                    publish_task_agent_event(task_id, "writeback", {
                        "shot_index": shot_row_data.get("shot_index"), "field": "selected_video",
                    })
                if transaction_id:
                    maybe_charge(transaction_id)
                publish_progress(task_id, status="running", progress=100,
                    stage_text=f"ComfyUI ({provider}) video generation complete",
                    retry_count=self.request.retries, celery_task_id=self.request.id)
                publish_complete(task_id, result, celery_task_id=self.request.id)
                return result

            # ── 传统 provider（Seedance / Kling，走 key_pool）──
            service_map = {
                "seedance": ("app.services.seedance", "seedance"),
                "kling": ("app.services.kling", "kling"),
            }
            module_name, pool_service = service_map.get(provider, ("app.services.seedance", "seedance"))

            key_name, api_key = key_pool.acquire(pool_service)
            publish_task_agent_event(task_id, "tool_call", {"tool": provider, "action": "acquire_key"})
            publish_task_agent_event(task_id, "tool_result", {"tool": "key_pool", "key_name": key_name})
            publish_progress(
                task_id,
                status="running",
                progress=15,
                stage_text=f"Calling {provider}",
                retry_count=self.request.retries,
                celery_task_id=self.request.id,
            )
            call = resolve_callable(module_name, ("generate_video", "generate"))
            publish_task_agent_event(task_id, "tool_call", {"tool": provider, "prompt": str(payload.get("prompt", ""))[:50]})
            _t0 = time.time()

            if provider == "seedance":
                try:
                    result = invoke_callable(call, payload, api_key=api_key, task_id=task_id, user_id=user_id)
                except PolicyViolationError:
                    payload["prompt"] = sanitize_prompt(payload.get("prompt", ""))
                    publish_progress(
                        task_id,
                        status="running",
                        progress=20,
                        stage_text="Policy violation, retrying with sanitized prompt...",
                        retry_count=self.request.retries,
                        celery_task_id=self.request.id,
                    )
                    try:
                        result = invoke_callable(call, payload, api_key=api_key, task_id=task_id, user_id=user_id)
                    except PolicyViolationError:
                        payload.pop("image_url", None)
                        payload.pop("ref_images", None)
                        result = invoke_callable(call, payload, api_key=api_key, task_id=task_id, user_id=user_id)
            else:
                result = invoke_callable(call, payload, api_key=api_key, task_id=task_id, user_id=user_id)
            result = persist_result_to_oss(result, "video")
            publish_task_agent_event(task_id, "tool_result", {
                "tool": provider, "url": str(result.get("url", ""))[:120], "duration_ms": int((time.time() - _t0) * 1000),
            })
            publish_task_agent_event(task_id, "artifact", {
                "type": "video", "size": result.get("file_size", 0), "duration": payload.get("duration", 5),
            })
            if shot_row_data:
                import asyncio
                url = result_url(result)
                review = review_video_candidate(shot_row_data, url)

                asyncio.run(update_shot_media(
                    str(shot_row_data.get("project_id") or ""),
                    int(shot_row_data.get("shot_index") or 0),
                    user_id,
                    video_url=url,
                    video_candidate=media_candidate(url, review),
                    status="video_done",
                ))
                publish_task_agent_event(task_id, "writeback", {
                    "shot_index": shot_row_data.get("shot_index"), "field": "selected_video",
                })
            maybe_charge(transaction_id)
            publish_progress(
                task_id,
                status="running",
                progress=100,
                stage_text=f"{provider} video generation complete",
                retry_count=self.request.retries,
                celery_task_id=self.request.id,
            )
            publish_complete(task_id, result, celery_task_id=self.request.id)
            return result
        except Exception as exc:
            error_decision = classify_exception(exc)
            retryable = error_decision.retryable
            publish_task_agent_event(task_id, "error", {
                "error": str(exc)[:200],
                "category": error_decision.category.value,
                "retryable": retryable,
                "retry_count": self.request.retries,
            })
            if key_name and error_decision.report_to_key_pool:
                key_pool.report_error(key_name, str(exc))
            if retryable and self.request.retries < MAX_RETRIES:
                # Reflect on failure before retrying — may adjust payload or skip
                strategy, adjusted_payload = reflect_before_retry(
                    task_id, exc,
                    retry_count=self.request.retries,
                    task_type="video_gen",
                    payload=payload,
                    shot_context=payload.get("shot_row"),
                )
                if strategy == "skip_shot":
                    # Reflection says this shot is unfixable — don't waste retries
                    retryable = False
                else:
                    publish_progress(
                        task_id,
                        status="retrying",
                        progress=15,
                        stage_text=f"Retrying video task ({self.request.retries + 1}/{MAX_RETRIES})",
                        retry_count=self.request.retries + 1,
                        celery_task_id=self.request.id,
                    )
                    raise self.retry(
                        exc=exc,
                        countdown=build_retry_delay(self.request.retries),
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
                dead_letter=error_decision.dead_letter,
                celery_task_id=self.request.id,
            )
            raise
    except Exception:
        # If publish_progress itself fails, re-raise with context
        # (no key_name to release at this point)
        raise
    finally:
        if key_name:
            key_pool.release(key_name)
        if locked_this_run:
            release_task_lock(task_id)
