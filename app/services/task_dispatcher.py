from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.middleware.rate_limit import check_concurrent_limit, check_rate_limit
from app.services.cost_guard import assert_cost_guard
from app.services.credits import credit_service
from app.services.task_submission import submit_single_task


@dataclass(frozen=True)
class TaskSpec:
    task_type: str
    celery_task_name: str
    queue: str
    credit_operation: str
    rate_resource: str | None = None


async def dispatch_task(
    db: AsyncSession,
    *,
    spec: TaskSpec,
    payload: dict[str, Any],
    user_id: int,
    user_tier: str,
) -> dict[str, Any]:
    await check_concurrent_limit(user_id, user_tier, db)
    if spec.rate_resource:
        await check_rate_limit(user_id, user_tier, spec.rate_resource, db)

    credits_reserved = await credit_service.get_price(spec.credit_operation)
    await assert_cost_guard(db, user_id=user_id, credits_to_reserve=credits_reserved)

    priority = _priority_for_tier(user_tier)
    submission = await submit_single_task(
        user_id=user_id,
        operation=spec.credit_operation,
        unit_price=credits_reserved,
        task_type=spec.task_type,
        celery_task_name=spec.celery_task_name,
        queue=spec.queue,
        priority=priority,
        payload=payload,
    )

    return {
        "task_id": submission.task_id,
        "status": "queued",
        "credits_reserved": submission.credits_reserved,
        "queue": spec.queue,
    }


def _priority_for_tier(user_tier: str) -> int:
    return {"free": 5, "pro": 3, "enterprise": 1}.get(str(user_tier or "").lower(), 5)
