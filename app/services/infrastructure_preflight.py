"""Infrastructure preflight guard for generation endpoints.

Checks that the underlying infrastructure (Redis broker, Celery workers,
Provider key pool) is healthy BEFORE accepting a batch generation request.
Raises HTTP 503 with a structured error if any check fails.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import HTTPException

from app.celery_app import celery_app
from app.redis_client import redis_client
from app.services.capacity_guard import check_capacity_sync

logger = logging.getLogger(__name__)

_CHECK_TIMEOUT = 3.0  # seconds per check

# Maps task_type -> Celery queue -> Provider key pool service
_TASK_INFRA_MAP: dict[str, dict[str, str]] = {
    "video_gen": {"queue": "video", "provider": "seedance"},
    "image_gen": {"queue": "image", "provider": "seedream"},
    "tts_gen": {"queue": "text", "provider": "doubao"},
    "video_production_run": {"queue": "video", "provider": "seedance"},
}


async def guard_infrastructure_preflight(task_type: str) -> None:
    """Verify infrastructure readiness before accepting a generation request.

    Checks in order:
      1. Redis (Celery broker) reachability
      2. Celery worker liveness for the target queue
      3. Provider key pool has at least one available key

    Raises HTTP 503 with ``failed_checks`` list if any check fails.
    """
    infra = _TASK_INFRA_MAP.get(task_type)
    if infra is None:
        logger.debug("infrastructure_preflight: no infra mapping for task_type=%s, skipping", task_type)
        return

    checks: dict[str, bool | str] = {}
    queue = infra["queue"]
    provider = infra["provider"]

    # 1. Redis (broker) reachability
    try:
        pong = await asyncio.wait_for(redis_client.ping(), timeout=_CHECK_TIMEOUT)
        checks["redis"] = bool(pong)
    except TimeoutError:
        logger.warning("infrastructure_preflight: redis ping timed out")
        checks["redis"] = "timeout"
    except Exception as exc:
        logger.warning("infrastructure_preflight: redis error: %s", exc)
        checks["redis"] = str(exc)

    # 2. Celery worker liveness for the target queue
    try:
        active = await asyncio.wait_for(
            asyncio.to_thread(_check_celery_queue_worker, queue),
            timeout=_CHECK_TIMEOUT,
        )
        checks[f"worker_{queue}"] = active
    except TimeoutError:
        logger.warning("infrastructure_preflight: celery worker check timed out for queue=%s", queue)
        checks[f"worker_{queue}"] = "timeout"
    except Exception as exc:
        logger.warning("infrastructure_preflight: celery worker error for queue=%s: %s", queue, exc)
        checks[f"worker_{queue}"] = str(exc)

    # 3. Provider key pool has available capacity
    try:
        capacity = await asyncio.wait_for(
            asyncio.to_thread(check_capacity_sync, provider),
            timeout=_CHECK_TIMEOUT,
        )
        has_available = capacity.available_slots > 0
        checks[f"provider_{provider}"] = has_available
        if not has_available:
            logger.warning(
                "infrastructure_preflight: provider %s saturated, available_slots=%d, cooldown=%s",
                provider, capacity.available_slots, capacity.cooldown_keys,
            )
    except TimeoutError:
        logger.warning("infrastructure_preflight: provider key pool check timed out for %s", provider)
        checks[f"provider_{provider}"] = "timeout"
    except Exception as exc:
        logger.warning("infrastructure_preflight: provider key pool error for %s: %s", provider, exc)
        checks[f"provider_{provider}"] = str(exc)

    failed = [name for name, ok in checks.items() if ok is not True]
    if failed:
        detail: dict[str, Any] = {
            "error": "infrastructure_preflight_blocked",
            "message": f"Infrastructure not ready: {', '.join(failed)}",
            "failed_checks": failed,
            "checks": {k: _summarise_check(v) for k, v in checks.items()},
        }
        logger.warning("infrastructure_preflight BLOCKED task_type=%s failed=%s", task_type, failed)
        raise HTTPException(status_code=503, detail=detail)

    logger.debug("infrastructure_preflight PASSED task_type=%s queue=%s provider=%s", task_type, queue, provider)


def _check_celery_queue_worker(queue: str) -> bool:
    """Check if at least one Celery worker consumes the given queue.

    Uses .active_queues() which is a lightweight broker inquiry.
    """
    result = celery_app.control.inspect(timeout=1.5).active_queues()
    if not result:
        return False
    for worker_name, queue_list in result.items():
        for q in queue_list:
            name = q.get("name") if isinstance(q, dict) else str(q)
            if name == queue:
                return True
    return False


def _summarise_check(value: bool | str) -> str:
    if value is True:
        return "ok"
    if value is False:
        return "failed"
    return str(value)
