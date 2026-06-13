from __future__ import annotations

from typing import Any

from app.celery_app import celery_app
from app.services.key_pool import key_pool
from app.tasks._shared import (
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
    resolve_callable,
)

MAX_RETRIES = 3


@celery_app.task(bind=True, queue="text", soft_time_limit=120, time_limit=240, acks_late=True)
def generate_tts_task(
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

    publish_progress(
        task_id,
        status="running",
        progress=5,
        stage_text="Preparing TTS task",
        retry_count=self.request.retries,
        celery_task_id=self.request.id,
    )
    key_name: str | None = None

    try:
        key_name, api_key = key_pool.acquire("doubao")
        publish_progress(
            task_id,
            status="running",
            progress=15,
            stage_text="Generating speech",
            retry_count=self.request.retries,
            celery_task_id=self.request.id,
        )
        call = resolve_callable(
            "app.services.tts",
            ("generate_speech", "generate_tts", "generate"),
        )
        result = invoke_callable(call, payload, api_key=api_key, task_id=task_id, user_id=user_id)
        result = persist_result_to_oss(result, "tts")
        maybe_charge(transaction_id)
        publish_complete(task_id, result, celery_task_id=self.request.id)
        return result
    except Exception as exc:
        retryable = is_retryable_exception(exc)
        if key_name and not isinstance(exc, TimeoutError):
            key_pool.report_error(key_name, str(exc))
        if retryable and self.request.retries < MAX_RETRIES:
            publish_progress(
                task_id,
                status="retrying",
                progress=15,
                stage_text=f"Retrying TTS ({self.request.retries + 1}/{MAX_RETRIES})",
                retry_count=self.request.retries + 1,
                celery_task_id=self.request.id,
            )
            raise self.retry(exc=exc, countdown=build_retry_delay(self.request.retries))

        refunded = maybe_refund(transaction_id)
        publish_failed(
            task_id,
            exc,
            retry_count=self.request.retries,
            credits_refunded=refunded,
            dead_letter=retryable,
            celery_task_id=self.request.id,
        )
        raise
    finally:
        if key_name:
            key_pool.release(key_name)
