from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import redis
from sqlalchemy import text

from app.celery_app import celery_app
from app.config import get_settings

logger = logging.getLogger(__name__)

_DISPATCH_RECEIPT_PREFIX = "dispatch:"


def _set_dispatch_receipt(task_id: str) -> None:
    """Write a lightweight receipt into broker Redis so the reconciler can
    confirm the message was delivered to the broker (O(1) EXISTS check).
    1-hour TTL — well past any expected task duration."""
    try:
        client = redis.Redis.from_url(
            get_settings().celery_broker_url, decode_responses=True
        )
        client.set(f"{_DISPATCH_RECEIPT_PREFIX}{task_id}", "", ex=3600)
        client.connection_pool.disconnect()
    except Exception:
        logger.exception("Failed to set dispatch receipt for task_id=%s", task_id)

PayloadFactory = Callable[[dict[str, Any], int], dict[str, Any]]
ReserveCredits = Callable[[int, str, int], Any]
AsyncSessionLocal: Any | None = None


@dataclass(frozen=True)
class BatchSubmissionResult:
    parent_task_id: str
    child_task_ids: list[str]
    total_credits_reserved: int


@dataclass(frozen=True)
class SingleSubmissionResult:
    task_id: str
    credits_reserved: int


async def submit_batch_tasks(
    *,
    user_id: int,
    operation: str,
    unit_price: int,
    task_type: str,
    celery_task_name: str,
    queue: str,
    priority: int,
    items: list[dict[str, Any]],
    payload_factory: PayloadFactory | None = None,
    reserve_func: ReserveCredits | None = None,
) -> BatchSubmissionResult:
    if not items:
        raise ValueError("items cannot be empty")

    transaction_ids = await _reserve_many(
        user_id=user_id,
        operation=operation,
        count=len(items),
        reserve_func=reserve_func,
    )
    parent_task_id = str(uuid.uuid4())
    child_task_ids: list[str] = []
    dispatch_payloads: list[dict[str, Any]] = []

    try:
        async with _get_session_local()() as session:
            async with session.begin():
                for index, item in enumerate(items):
                    task_id = str(uuid.uuid4())
                    task_payload = _build_payload(item, index, payload_factory)
                    dispatch_payloads.append(task_payload)
                    child_task_ids.append(task_id)
                    await _insert_queued_task(
                        session,
                        task_id=task_id,
                        user_id=user_id,
                        task_type=task_type,
                        priority=priority,
                        payload=task_payload,
                        credits_reserved=unit_price,
                        transaction_id=transaction_ids[index],
                    )
    except Exception:
        await _refund_reserved_credits(transaction_ids, reason=f"{task_type} task creation failure")
        raise

    dispatched_count = 0
    try:
        for index, task_id in enumerate(child_task_ids):
            celery_app.send_task(
                celery_task_name,
                args=[task_id, str(user_id), dispatch_payloads[index]],
                kwargs={"transaction_id": transaction_ids[index]},
                queue=queue,
                priority=priority,
            )
            _set_dispatch_receipt(task_id)
            dispatched_count += 1
    except Exception as exc:
        pending_task_ids = child_task_ids[dispatched_count:]
        pending_transaction_ids = transaction_ids[dispatched_count:]
        logger.error(
            "Batch task dispatch failed task_type=%s queue=%s user_id=%s dispatched=%d pending_task_ids=%s pending_transaction_ids=%s: %s",
            task_type,
            queue,
            user_id,
            dispatched_count,
            pending_task_ids,
            pending_transaction_ids,
            exc,
        )
        await _refund_reserved_credits(
            pending_transaction_ids,
            reason=f"{task_type} task dispatch failure",
        )
        await _mark_tasks_failed(pending_task_ids, f"{task_type} dispatch failed before worker start: {exc}")
        raise

    return BatchSubmissionResult(
        parent_task_id=parent_task_id,
        child_task_ids=child_task_ids,
        total_credits_reserved=len(items) * unit_price,
    )


async def submit_single_task(
    *,
    user_id: int,
    operation: str,
    unit_price: int,
    task_type: str,
    celery_task_name: str,
    queue: str,
    priority: int,
    payload: dict[str, Any],
    reserve_func: ReserveCredits | None = None,
) -> SingleSubmissionResult:
    reserve_func = reserve_func or _get_reserve_credits()
    transaction_id = await reserve_func(user_id, operation, 1)
    task_id = str(uuid.uuid4())

    try:
        async with _get_session_local()() as session:
            async with session.begin():
                await _insert_queued_task(
                    session,
                    task_id=task_id,
                    user_id=user_id,
                    task_type=task_type,
                    priority=priority,
                    payload=payload,
                    credits_reserved=unit_price,
                    transaction_id=transaction_id,
                )
    except Exception:
        await _refund_reserved_credits([transaction_id], reason=f"{task_type} task creation failure")
        raise

    try:
        celery_app.send_task(
            celery_task_name,
            args=[task_id, str(user_id), payload],
            kwargs={"transaction_id": transaction_id},
            queue=queue,
            priority=priority,
        )
        _set_dispatch_receipt(task_id)
    except Exception as exc:
        logger.error(
            "Single task dispatch failed task_id=%s task_type=%s queue=%s user_id=%s transaction_id=%s: %s",
            task_id,
            task_type,
            queue,
            user_id,
            transaction_id,
            exc,
        )
        await _refund_reserved_credits([transaction_id], reason=f"{task_type} task dispatch failure")
        await _mark_tasks_failed([task_id], f"{task_type} dispatch failed before worker start: {exc}")
        raise

    return SingleSubmissionResult(task_id=task_id, credits_reserved=unit_price)


def _build_payload(
    item: dict[str, Any],
    index: int,
    payload_factory: PayloadFactory | None,
) -> dict[str, Any]:
    source = dict(item)
    if payload_factory is None:
        return source
    built = payload_factory(source, index)
    if not isinstance(built, dict):
        raise TypeError("payload_factory must return a dict")
    return built


async def _insert_queued_task(
    session: Any,
    *,
    task_id: str,
    user_id: int,
    task_type: str,
    priority: int,
    payload: dict[str, Any],
    credits_reserved: int,
    transaction_id: str,
) -> None:
    db_payload = {**payload, "_credit_transaction_id": transaction_id}
    await session.execute(
        text(
            """
            INSERT INTO tasks (
                task_id, user_id, task_type, status,
                priority, payload, credits_reserved, credit_transaction_id
            )
            VALUES (
                :task_id, :user_id, :task_type, 'queued',
                :priority, :payload, :credits_reserved, :credit_transaction_id
            )
            """
        ),
        {
            "task_id": task_id,
            "user_id": user_id,
            "task_type": task_type,
            "priority": priority,
            "payload": json.dumps(db_payload, ensure_ascii=False, default=str),
            "credits_reserved": credits_reserved,
            "credit_transaction_id": transaction_id,
        },
    )


async def _reserve_many(
    *,
    user_id: int,
    operation: str,
    count: int,
    reserve_func: ReserveCredits | None,
) -> list[str]:
    reserve_func = reserve_func or _get_reserve_credits()
    transaction_ids: list[str] = []
    try:
        for _ in range(count):
            transaction_ids.append(await reserve_func(user_id, operation, 1))
    except Exception:
        await _refund_reserved_credits(transaction_ids, reason=f"{operation} credit reservation failure")
        raise
    return transaction_ids


async def _refund_reserved_credits(transaction_ids: list[str], *, reason: str) -> None:
    for transaction_id in transaction_ids:
        try:
            from app.services.credits import credit_service

            await credit_service.refund(transaction_id)
        except Exception as exc:
            logger.error(
                "Failed to refund reserved credits transaction_id=%s reason=%s: %s",
                transaction_id,
                reason,
                exc,
            )


async def _mark_tasks_failed(task_ids: list[str], message: str) -> None:
    if not task_ids:
        return
    async with _get_session_local()() as session:
        async with session.begin():
            for task_id in task_ids:
                await session.execute(
                    text(
                        """
                        UPDATE tasks
                        SET status = 'failed',
                            error_message = :message,
                            completed_at = NOW(),
                            updated_at = NOW()
                        WHERE task_id = CAST(:task_id AS uuid)
                        """
                    ),
                    {"task_id": task_id, "message": message[:500]},
                )


def _get_session_local() -> Any:
    global AsyncSessionLocal
    if AsyncSessionLocal is None:
        from app.db import AsyncSessionLocal as session_local

        AsyncSessionLocal = session_local
    return AsyncSessionLocal


def _get_reserve_credits() -> ReserveCredits:
    from app.middleware.credits import reserve_credits

    return reserve_credits
