from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import redis

from sqlalchemy import text

from app.celery_app import celery_app
from app.config import get_settings
from app.db import AsyncSessionLocal
from app.services.key_pool import key_pool

logger = logging.getLogger(__name__)

# Dispatch receipt prefix — the same constant used in task_submission.py / _shared.py
_DISPATCH_RECEIPT_PREFIX = "dispatch:"


@celery_app.task(queue="admin")
def refresh_key_pool_state() -> dict[str, list[dict[str, object]]]:
    return key_pool.snapshot()


@celery_app.task(queue="admin")
def expire_credit_reservations() -> dict[str, str]:
    return {
        "status": "noop",
        "detail": "Credit reservations are finalized or refunded explicitly by worker tasks.",
    }


@celery_app.task(queue="admin")
def worker_healthcheck() -> dict[str, object]:
    snapshot = key_pool.snapshot()
    return {
        "queues": ["video", "image", "text", "admin"],
        "services": sorted(snapshot.keys()),
        "keys_loaded": sum(len(records) for records in snapshot.values()),
    }


@celery_app.task(queue="admin")
def cleanup_stale_tasks(
    running_timeout_minutes: int = 120,
    queued_timeout_minutes: int = 30,
) -> dict[str, int]:
    return asyncio.run(_cleanup_stale_tasks_async(running_timeout_minutes, queued_timeout_minutes))


async def _cleanup_stale_tasks_async(running_timeout_minutes: int, queued_timeout_minutes: int) -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            running_result = await session.execute(
                text(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        stage_text = 'Failed',
                        error_message = :running_error,
                        completed_at = NOW(),
                        updated_at = NOW()
                    WHERE status = 'running'
                      AND updated_at < NOW() - make_interval(mins => :running_timeout_minutes)
                    """
                ),
                {
                    "running_timeout_minutes": int(running_timeout_minutes),
                    "running_error": f"Task cleaned automatically: stale running task exceeded {int(running_timeout_minutes)} minutes without update.",
                },
            )
            queued_result = await session.execute(
                text(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        stage_text = 'Failed',
                        error_message = :queued_error,
                        completed_at = NOW(),
                        updated_at = NOW()
                    WHERE status = 'queued'
                      AND created_at < NOW() - make_interval(mins => :queued_timeout_minutes)
                    """
                ),
                {
                    "queued_timeout_minutes": int(queued_timeout_minutes),
                    "queued_error": f"Task cleaned automatically: stale queued task exceeded {int(queued_timeout_minutes)} minutes without execution.",
                },
            )

    return {
        "running_cleaned": int(running_result.rowcount or 0),
        "queued_cleaned": int(queued_result.rowcount or 0),
        "running_timeout_minutes": int(running_timeout_minutes),
        "queued_timeout_minutes": int(queued_timeout_minutes),
    }


@celery_app.task(queue="admin")
def reconcile_orphaned_tasks(
    queued_timeout_seconds: int = 180,
    max_attempts: int = 3,
    batch_size: int = 50,
) -> dict[str, Any]:
    """Detect and re-dispatch tasks stuck in 'queued' state whose broker
    message was lost (DB-broker split-brain). Runs every 60s via beat.

    Uses a lightweight dispatch-receipt EXISTS check (O(1) per task)
    instead of scanning broker queue lists.
    """
    return asyncio.run(
        _reconcile_orphaned_tasks_async(
            queued_timeout_seconds=queued_timeout_seconds,
            max_attempts=max_attempts,
            batch_size=batch_size,
        )
    )


async def _reconcile_orphaned_tasks_async(
    queued_timeout_seconds: int,
    max_attempts: int,
    batch_size: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "scanned": 0,
        "redispatched": 0,
        "skipped_in_queue": 0,
        "abandoned": 0,
        "errors": 0,
    }

    async with AsyncSessionLocal() as session:
        # Fetch candidate orphan tasks
        rows = (
            await session.execute(
                text(
                    """
                    SELECT task_id::text, task_type, priority, payload,
                           credit_transaction_id, reconcile_attempts, celery_task_id
                    FROM tasks
                    WHERE status = 'queued'
                      AND created_at < NOW() - make_interval(secs => :timeout_secs)
                      AND (reconcile_attempts IS NULL OR reconcile_attempts < :max_attempts)
                    ORDER BY created_at ASC
                    LIMIT :batch_size
                    """
                ),
                {
                    "timeout_secs": int(queued_timeout_seconds),
                    "max_attempts": int(max_attempts),
                    "batch_size": int(batch_size),
                },
            )
        ).fetchall()

    if not rows:
        return {**result, "scanned": 0}

    result["scanned"] = len(rows)

    # Batch-check dispatch receipts via broker Redis
    broker_receipts = _check_dispatch_receipts_broker(
        [str(r[0]) for r in rows]
    )
    # broker_receipts: {task_id: True/False} — True means message IS in broker

    for row in rows:
        task_id = str(row[0])
        task_type = str(row[1])
        priority = int(row[2])
        payload_raw = row[3]
        transaction_id = row[4]
        reconcile_attempts = (row[5] or 0) + 1
        celery_task_id = row[6]

        # Skip if the dispatch receipt exists — worker will eventually pick it up
        if broker_receipts.get(task_id):
            result["skipped_in_queue"] += 1
            # Bump updated_at so the 30-min stale-cleanup doesn't kill it
            await _touch_task(task_id)
            continue

        # Orphan confirmed: re-dispatch or abandon
        if reconcile_attempts >= max_attempts:
            await _abandon_task(task_id, transaction_id)
            result["abandoned"] += 1
            logger.warning(
                "Task abandoned after %d reconcile attempts task_id=%s task_type=%s",
                reconcile_attempts, task_id, task_type,
            )
            continue

        # Attempt re-dispatch
        try:
            _redispatch_task(task_id, task_type, priority, payload_raw, transaction_id, celery_task_id)
            result["redispatched"] += 1
            logger.info(
                "Task re-dispatched task_id=%s task_type=%s attempt=%d/%d",
                task_id, task_type, reconcile_attempts, max_attempts,
            )
        except Exception as exc:
            result["errors"] += 1
            logger.exception(
                "Re-dispatch failed task_id=%s task_type=%s attempt=%d/%d: %s",
                task_id, task_type, reconcile_attempts, max_attempts, exc,
            )

        # Update reconcile_attempts counter regardless
        await _increment_reconcile_attempts(task_id, reconcile_attempts)

    return result


def _check_dispatch_receipts_broker(task_ids: list[str]) -> dict[str, bool]:
    """Batch-EXISTS check of dispatch receipts via Celery broker Redis."""
    if not task_ids:
        return {}
    try:
        client = redis.Redis.from_url(
            get_settings().celery_broker_url, decode_responses=True
        )
        pipe = client.pipeline(transaction=False)
        for tid in task_ids:
            pipe.exists(f"{_DISPATCH_RECEIPT_PREFIX}{tid}")
        raw = pipe.execute()
        client.connection_pool.disconnect()
        return dict(zip(task_ids, [bool(v) for v in raw]))
    except Exception as exc:
        logger.error("Broker receipt check failed: %s", exc)
        return {}


def _redispatch_task(
    task_id: str,
    task_type: str,
    priority: int,
    payload_raw: Any,
    transaction_id: str | None,
    celery_task_id: str | None,
) -> None:
    """Re-send the task to Celery broker, restoring its dispatch receipt.
    Let Celery generate a new internal message ID — duplicates are
    prevented by the idempotency lock at worker entry."""
    celery_task_name = _resolve_celery_task_name(task_type)
    queue = _resolve_queue(task_type)
    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw

    celery_app.send_task(
        celery_task_name,
        args=[task_id, payload.get("user_id", "0"), payload],
        kwargs={"transaction_id": transaction_id} if transaction_id else None,
        queue=queue,
        priority=priority,
    )

    # Re-create dispatch receipt
    _set_dispatch_receipt(task_id)


def _set_dispatch_receipt(task_id: str) -> None:
    """Set dispatch receipt in broker Redis (TTL 1 hour)."""
    try:
        client = redis.Redis.from_url(
            get_settings().celery_broker_url, decode_responses=True
        )
        client.set(f"{_DISPATCH_RECEIPT_PREFIX}{task_id}", "", ex=3600)
        client.connection_pool.disconnect()
    except Exception as exc:
        logger.warning("Failed to set dispatch receipt for %s: %s", task_id, exc)


def _resolve_celery_task_name(task_type: str) -> str:
    """Map DB task_type to Celery task name."""
    mapping = {
        "video_gen": "app.tasks.video_tasks.generate_video_task",
        "image_gen": "app.tasks.image_tasks.generate_image_task",
        "tts_gen": "app.tasks.text_tasks.generate_tts_task",
        "text_gen": "app.tasks.text_tasks.generate_text_task",
    }
    return mapping.get(task_type, "app.tasks.video_tasks.generate_video_task")


def _resolve_queue(task_type: str) -> str:
    mapping = {
        "video_gen": "video",
        "image_gen": "image",
        "tts_gen": "text",
        "text_gen": "text",
    }
    return mapping.get(task_type, "default")


async def _increment_reconcile_attempts(task_id: str, attempts: int) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                """
                UPDATE tasks
                SET reconcile_attempts = :attempts, updated_at = NOW()
                WHERE task_id = CAST(:task_id AS uuid)
                """
            ),
            {"task_id": task_id, "attempts": int(attempts)},
        )
        await session.commit()


async def _touch_task(task_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "UPDATE tasks SET updated_at = NOW() WHERE task_id = CAST(:task_id AS uuid)"
            ),
            {"task_id": task_id},
        )
        await session.commit()


async def _abandon_task(task_id: str, transaction_id: str | None) -> None:
    """Mark task as failed and refund credits."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        stage_text = 'Abandoned',
                        error_message = 'Task abandoned after max reconcile attempts: broker message lost and re-dispatch exhausted.',
                        completed_at = NOW(),
                        updated_at = NOW()
                    WHERE task_id = CAST(:task_id AS uuid)
                    """
                ),
                {"task_id": task_id},
            )
    if transaction_id:
        try:
            from app.services.credits import credit_service
            await credit_service.refund(transaction_id)
        except Exception as exc:
            logger.error("Refund failed for abandoned task %s tx=%s: %s", task_id, transaction_id, exc)


@celery_app.task(queue="admin")
def process_work_queue() -> dict[str, int]:
    """Drain the work queue for all services with available Key Pool capacity."""
    from app.services.work_queue import process_all
    return process_all()
