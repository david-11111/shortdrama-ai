"""Redis-backed priority work queue for provider task dispatch.

Key improvements over the original:
1. ``_ensure_db_task`` uses ``app.core.async_bridge.run_async()`` instead
   of ``asyncio.run()``, which crashes if called from a running event loop.
2. ``process_all`` uses a ``while`` loop to drain the entire queue
   until capacity is exhausted or the queue is empty (was: one dequeue
   per service).
3. Redis pipeline used where possible to reduce RTT.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import redis

from app.config import get_settings
from app.core.async_bridge import run_async
from app.services.capacity_guard import check_capacity_sync

logger = logging.getLogger(__name__)

_PRIORITY_BASE = 1_000_000_000_000
QUEUE_SERVICES = ["seedance", "seedream", "kling"]
_DB_TASK_TTL = 86_400  # 24 hours


def _client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def _pending_key(service: str) -> str:
    return f"work_queue:{service}:pending"


def _task_key(service: str, task_id: str) -> str:
    return f"work_queue:{service}:task:{task_id}"


def enqueue(
    *,
    service: str,
    task_id: str,
    celery_task: str,
    args: list[Any],
    kwargs: dict[str, Any],
    queue: str,
    priority: int = 5,
) -> int:
    """Add a task to the priority queue. Returns queue position (1-based)."""
    client = _client()
    try:
        pipe = client.pipeline()
        pipe.hset(_task_key(service, task_id), mapping={
            "celery_task": celery_task,
            "args_json": json.dumps(args, ensure_ascii=False, default=str),
            "kwargs_json": json.dumps(kwargs, ensure_ascii=False, default=str),
            "queue": queue,
            "priority": str(priority),
            "enqueued_at": str(time.time()),
        })
        pipe.expire(_task_key(service, task_id), _DB_TASK_TTL)
        score = int(priority) * _PRIORITY_BASE + int(time.time() * 1000)
        pipe.zadd(_pending_key(service), {task_id: score})
        pipe.zrank(_pending_key(service), task_id)
        results = pipe.execute()
        rank = results[-1]
        return (rank + 1) if rank is not None else 1
    finally:
        client.close()


def dequeue(service: str) -> dict[str, Any] | None:
    """Pop the highest-priority task from the queue. Returns None if empty."""
    client = _client()
    try:
        result = client.zpopmin(_pending_key(service), count=1)
        if not result:
            return None
        task_id = result[0][0]
        pipe = client.pipeline()
        pipe.hgetall(_task_key(service, task_id))
        pipe.delete(_task_key(service, task_id))
        pipe_data, _ = pipe.execute()
        if not pipe_data:
            return None
        return {
            "task_id": task_id,
            "celery_task": pipe_data.get("celery_task", ""),
            "args": json.loads(pipe_data.get("args_json", "[]")),
            "kwargs": json.loads(pipe_data.get("kwargs_json", "{}")),
            "queue": pipe_data.get("queue", "default"),
            "priority": int(pipe_data.get("priority", "5")),
        }
    finally:
        client.close()


def queue_length(service: str) -> int:
    """Return the number of pending tasks for a service."""
    client = _client()
    try:
        return client.zcard(_pending_key(service))
    finally:
        client.close()


def queue_position(service: str, task_id: str) -> int:
    """Return the 1-based position of a task in the queue, or 0 if not found."""
    client = _client()
    try:
        rank = client.zrank(_pending_key(service), task_id)
        return (rank + 1) if rank is not None else 0
    finally:
        client.close()


def _ensure_db_task(task: dict[str, Any]) -> None:
    """Create a DB task record for a work-queue task before Celery dispatch.

    Uses ``app.core.async_bridge.run_async()`` instead of raw
    ``asyncio.run()`` so it works correctly inside a running event loop.
    """
    async def _insert() -> None:
        from app.db import AsyncSessionLocal
        from sqlalchemy import text

        args = task.get("args", [])
        task_id = task.get("task_id", "")
        user_id = int(args[1]) if len(args) > 1 else 0
        payload = args[2] if len(args) > 2 else {}
        project_id = payload.get("project_id", "") if isinstance(payload, dict) else ""
        run_id = payload.get("run_id", "") if isinstance(payload, dict) else ""
        task_type = "video_gen" if "video" in str(task.get("celery_task", "")) else "image_gen"
        priority = int(task.get("priority", 5))
        shot_index = payload.get("shot_index", 0) if isinstance(payload, dict) else 0

        async with AsyncSessionLocal() as db:
            await db.execute(
                text("""
                    INSERT INTO tasks (task_id, user_id, project_id, run_id, task_type, status, priority, payload)
                    VALUES (CAST(:tid AS UUID), :uid, :pid, CAST(:rid AS UUID), :ttype, 'queued', :pri, :payload)
                    ON CONFLICT (task_id) DO NOTHING
                """),
                {
                    "tid": task_id, "uid": user_id, "pid": project_id,
                    "rid": run_id or None, "ttype": task_type, "pri": priority,
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                },
            )
            await db.commit()

    try:
        run_async(_insert())
    except Exception as exc:
        logger.warning("work_queue: DB insert failed for %s: %s", task.get("task_id", "?"), exc)


def process_all() -> dict[str, int]:
    """Called by Celery beat: drain all queues while capacity permits.

    Returns ``{service: dequeued_count}`` for monitoring.

    ⚠️ Changed from original: now drains *all* available tasks per
    service (was: one per service per beat tick).
    """
    results: dict[str, int] = {}
    from app.celery_app import celery_app

    for service in QUEUE_SERVICES:
        count = 0
        while True:
            capacity = check_capacity_sync(service)
            if capacity.total_concurrency <= 0 or capacity.available_slots <= 0:
                break
            task = dequeue(service)
            if task is None:
                break
            try:
                _ensure_db_task(task)
                celery_app.send_task(
                    task["celery_task"],
                    args=task["args"],
                    kwargs=task["kwargs"],
                    queue=task["queue"],
                    priority=task["priority"],
                )
                count += 1
            except Exception as exc:
                logger.warning("work_queue: failed to dispatch %s: %s", task.get("task_id", "?"), exc)
                enqueue(
                    service=service,
                    task_id=task["task_id"],
                    celery_task=task["celery_task"],
                    args=task["args"],
                    kwargs=task["kwargs"],
                    queue=task["queue"],
                    priority=task["priority"],
                )
                break  # Stop draining on error

        if count:
            logger.info("work_queue: processed %d tasks from %s queue", count, service)
        results[service] = count

    return results
