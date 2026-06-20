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
from app.services.video_provider import dispatch as router_dispatch, get_config
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


def _writeback_video(
    task_id: str,
    user_id: str,
    shot_row_data: dict[str, Any] | None,
    url: str,
    transaction_id: str | None = None,
) -> None:
    """统一写回 shot_rows + 计费（3 条 provider 路径的重复代码合并）。"""
    import asyncio

    if shot_row_data:
        review = review_video_candidate(shot_row_data, url)
        asyncio.run(update_shot_media(
            str(shot_row_data.get("project_id") or ""),
            int(shot_row_data.get("shot_index") or 0),
            str(shot_row_data.get("user_id") or user_id),
            video_url=url,
            video_candidate=media_candidate(url, review),
            status="video_done",
        ))
        publish_task_agent_event(task_id, "writeback", {
            "shot_index": shot_row_data.get("shot_index"), "field": "selected_video",
        })
    if transaction_id:
        maybe_charge(transaction_id)


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
    else:
        return {"status": "duplicate", "task_id": task_id}

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
            provider = str(payload.get("provider", "joy-echo")).lower()
            cfg = get_config(provider)
            text_only_provider = cfg.text_only if cfg else False

            shot_row_data = payload.get("shot_row")
            if shot_row_data:
                if shot_row_data.get("image_url") and not shot_row_data.get("selected_image"):
                    shot_row_data["selected_image"] = shot_row_data["image_url"]
                resolved = build_video_generation_payload(shot_row_data, strict=False)
                if resolved.get("prompt"):
                    payload["prompt"] = resolved["prompt"]
                if resolved.get("duration"):
                    payload["duration"] = resolved["duration"]
                if not text_only_provider and resolved.get("image") and not payload.get("image_url"):
                    payload["image_url"] = resolved["image"]
                if not text_only_provider and resolved.get("subject_reference"):
                    payload.setdefault("ref_images", []).extend(resolved["subject_reference"])

            payload = adapt_provider_payload(payload, task_type="video_gen", provider=provider)
            if text_only_provider:
                payload.pop("image_url", None)
                payload.pop("ref_images", None)

            # ── 通过统一路由层调用（换 provider 只需换 payload 里的 provider 名）──
            publish_task_agent_event(task_id, "tool_call", {"tool": provider, "action": f"{provider}_submit"})
            publish_progress(
                task_id, status="running", progress=15,
                stage_text=f"Calling {provider}",
                retry_count=self.request.retries,
                celery_task_id=self.request.id,
            )
            _t0 = time.time()

            # Seedance 特殊处理：PolicyViolation 重试 + sanitize
            if provider == "seedance":
                try:
                    result = router_dispatch(payload)
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
                        result = router_dispatch(payload)
                    except PolicyViolationError:
                        payload.pop("image_url", None)
                        payload.pop("ref_images", None)
                        result = router_dispatch(payload)
            else:
                result = router_dispatch(payload)

            # 对走 key_pool 的 provider 做 OSS 持久化
            if cfg and cfg.needs_key:
                result = persist_result_to_oss(
                    {"url": result["url"], **result.get("extra", {})}, "video"
                )
                url = result_url(result)
            else:
                url = result["url"]

            publish_task_agent_event(task_id, "tool_result", {
                "tool": provider, "url": url[:120],
                "duration_ms": int((time.time() - _t0) * 1000),
            })

            _writeback_video(task_id, user_id, shot_row_data, url, transaction_id)

            publish_progress(
                task_id, status="running", progress=100,
                stage_text=f"{provider} video generation complete",
                retry_count=self.request.retries, celery_task_id=self.request.id,
            )
            publish_complete(task_id, {"url": url}, celery_task_id=self.request.id)
            return {"url": url}
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
                        args=(task_id, user_id, adjusted_payload),
                        kwargs={"transaction_id": transaction_id},
                    )

            refunded = maybe_refund(transaction_id)
            shot_row_data = payload.get("shot_row")
            if shot_row_data:
                import asyncio

                error_text = str(exc)
                asyncio.run(update_shot_error(
                    str(shot_row_data.get("project_id") or ""),
                    int(shot_row_data.get("shot_index") or 0),
                    str(shot_row_data.get("user_id") or user_id),
                    error_text,
                    status="image_done" if shot_row_data.get("selected_image") else "error",
                    preserve_selected_video=True,
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
