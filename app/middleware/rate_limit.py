import time

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.redis_client import make_redis_client


async def check_rate_limit(user_id: int, tier: str, resource: str, db: AsyncSession) -> dict:
    """
    Check sliding-window rate limit from rate_limit_config.

    A fresh Redis async client is used per call so Celery workers do not reuse
    loop-bound redis.asyncio connections across asyncio.run() event loops.
    """
    result = await db.execute(
        text("SELECT window_seconds, max_count FROM rate_limit_config WHERE tier = :tier AND resource = :resource"),
        {"tier": tier, "resource": resource},
    )
    row = result.fetchone()
    if not row:
        return {"remaining": -1, "limit": -1, "reset_at": 0}

    window_seconds = row.window_seconds
    max_count = row.max_count

    redis_key = f"rate_limit:{user_id}:{resource}"
    now = time.time()
    window_start = now - window_seconds

    client = make_redis_client()
    try:
        pipe = client.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zcard(redis_key)
        results = await pipe.execute()
        current_count = results[1]

        if current_count >= max_count:
            earliest = await client.zrange(redis_key, 0, 0, withscores=True)
            retry_after = int(window_seconds - (now - earliest[0][1])) if earliest else window_seconds
            retry_after = max(retry_after, 1)
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "resource": resource,
                    "limit": max_count,
                    "window_seconds": window_seconds,
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_count),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(now + retry_after)),
                    "X-RateLimit-Resource": resource,
                },
            )

        await client.zadd(redis_key, {f"{now}": now})
        await client.expire(redis_key, window_seconds + 10)
    finally:
        await client.aclose()

    return {
        "remaining": max_count - current_count - 1,
        "limit": max_count,
        "reset_at": int(now + window_seconds),
    }


async def check_concurrent_limit(user_id: int, tier: str, db: AsyncSession) -> None:
    """
    Check concurrent task limit by counting queued/running tasks for the user.
    """
    result = await db.execute(
        text("SELECT max_count FROM rate_limit_config WHERE tier = :tier AND resource = 'concurrent_tasks'"),
        {"tier": tier},
    )
    row = result.fetchone()
    if not row:
        return

    max_concurrent = row.max_count

    count_result = await db.execute(
        text("SELECT COUNT(*) FROM tasks WHERE user_id = :uid AND status IN ('queued', 'running')"),
        {"uid": user_id},
    )
    current = count_result.scalar()

    if current >= max_concurrent:
        retry_after = 2
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Concurrent task limit exceeded",
                "current": current,
                "limit": max_concurrent,
                "retry_after": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(max_concurrent),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time() + retry_after)),
                "X-RateLimit-Resource": "concurrent_tasks",
            },
        )
