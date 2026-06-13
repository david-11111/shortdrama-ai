# T8 指令 — api-biz 终端

## 你的身份

你是 `api-biz` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 前置条件

Phase 2 已完成：
- `app/middleware/auth.py` — `get_current_user` 返回含 `id`、`tier` 的用户 dict
- `app/services/credits.py` — `credit_service`（reserve/charge/refund）
- `app/services/key_pool.py` — `key_pool`（acquire/release/report_error）
- `app/routes/credits.py` — 积分查询端点已就绪
- `alembic/versions/001_initial_schema.py` — `rate_limit_config` 表已有种子数据

`rate_limit_config` 表数据：
```
free:  concurrent_tasks=2, video_gen=5/h, image_gen=20/h
pro:   concurrent_tasks=10, video_gen=50/h, image_gen=200/h
enterprise: concurrent_tasks=50, video_gen=200/h, image_gen=1000/h
```

## 任务目标

实现限流中间件 + 积分预扣集成到批量生成端点。用户请求时：鉴权 → 积分检查/预扣 → 限流检查 → 派发任务。

## 分支

```bash
git checkout -b api/phase3-rate-limit
```

## 需要创建/修改的文件

### 1. `app/middleware/rate_limit.py`（新建）

Redis 滑动窗口限流：

```python
"""
限流中间件 — Redis 滑动窗口。

使用方式:
    from app.middleware.rate_limit import check_rate_limit

    # 在路由中调用
    await check_rate_limit(user_id=current_user["id"], tier=current_user["tier"], resource="video_gen")

限流逻辑:
- 从 rate_limit_config 表读取配置（按 tier + resource）
- 使用 Redis ZSET 实现滑动窗口
- 超限返回 429 + retry-after header
"""
import time

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.redis_client import redis_client


async def check_rate_limit(user_id: int, tier: str, resource: str, db: AsyncSession) -> dict:
    """
    检查限流。通过返回 {"remaining": N, "limit": M, "reset_at": timestamp}。
    超限抛 HTTPException(429)。
    """
    # 查配置
    result = await db.execute(
        text("SELECT window_seconds, max_count FROM rate_limit_config WHERE tier = :tier AND resource = :resource"),
        {"tier": tier, "resource": resource},
    )
    row = result.fetchone()
    if not row:
        # 无配置则不限流
        return {"remaining": -1, "limit": -1, "reset_at": 0}

    window_seconds = row.window_seconds
    max_count = row.max_count

    # Redis 滑动窗口 (Sorted Set)
    redis_key = f"rate_limit:{user_id}:{resource}"
    now = time.time()
    window_start = now - window_seconds

    pipe = redis_client.pipeline()
    # 移除窗口外的记录
    pipe.zremrangebyscore(redis_key, 0, window_start)
    # 统计窗口内的请求数
    pipe.zcard(redis_key)
    results = await pipe.execute()
    current_count = results[1]

    if current_count >= max_count:
        # 计算最早记录的过期时间作为 retry-after
        earliest = await redis_client.zrange(redis_key, 0, 0, withscores=True)
        retry_after = int(window_seconds - (now - earliest[0][1])) if earliest else window_seconds
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "resource": resource,
                "limit": max_count,
                "window_seconds": window_seconds,
                "retry_after": max(retry_after, 1),
            },
            headers={"Retry-After": str(max(retry_after, 1))},
        )

    # 记录本次请求
    await redis_client.zadd(redis_key, {f"{now}": now})
    await redis_client.expire(redis_key, window_seconds + 10)  # TTL 略大于窗口

    return {
        "remaining": max_count - current_count - 1,
        "limit": max_count,
        "reset_at": int(now + window_seconds),
    }


async def check_concurrent_limit(user_id: int, tier: str, db: AsyncSession) -> None:
    """
    检查并发任务数限制。
    统计 tasks 表中 status IN ('queued', 'running') 的数量。
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
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Concurrent task limit exceeded",
                "current": current,
                "limit": max_concurrent,
            },
        )
```

### 2. `app/middleware/credits.py`（新建）

积分预扣中间件：

```python
"""
积分预扣中间件。

在任务派发前调用，预扣积分。
任务成功后由 worker 调用 charge 确认。
任务失败后由 worker 调用 refund 退还。
"""
from fastapi import HTTPException

from app.services.credits import credit_service, InsufficientCreditsError


async def reserve_credits(user_id: int, operation: str, quantity: int = 1) -> str:
    """
    预扣积分。返回 transaction_id。
    余额不足抛 HTTPException(402)。
    """
    try:
        transaction_id = credit_service.reserve(user_id, operation, quantity)
        return transaction_id
    except InsufficientCreditsError as e:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Insufficient credits",
                "message": str(e),
                "operation": operation,
                "quantity": quantity,
            },
        )
```

### 3. `app/main.py` 改造

将限流和积分预扣集成到批量生成端点：

```python
from app.middleware.rate_limit import check_rate_limit, check_concurrent_limit
from app.middleware.credits import reserve_credits
from app.db import get_db

@app.post("/api/batch/generate-videos", status_code=202, response_model=BatchTaskSubmitResponse)
async def batch_generate_videos(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    完整流程: 鉴权 → 并发检查 → 限流检查 → 积分预扣 → 派发任务
    """
    user_id = current_user["id"]
    user_tier = current_user["tier"]
    items = payload.get("items", [])
    quantity = len(items)

    # 1. 并发任务数检查
    await check_concurrent_limit(user_id, user_tier, db)

    # 2. 限流检查（视频生成频率）
    await check_rate_limit(user_id, user_tier, "video_gen", db)

    # 3. 积分预扣（按视频时长计算，默认 video_gen_5s）
    # TODO: 根据 item 中的 duration 字段选择不同定价
    operation = "video_gen_5s"
    transaction_id = await reserve_credits(user_id, operation, quantity)

    # 4. 派发任务
    priority_map = {"free": 5, "pro": 3, "enterprise": 1}
    priority = priority_map.get(user_tier, 5)
    parent_task_id = str(uuid.uuid4())
    child_task_ids = []

    async with AsyncSessionLocal() as session:
        async with session.begin():
            for item in items:
                child_id = str(uuid.uuid4())
                child_task_ids.append(child_id)

                await session.execute(
                    text("""
                        INSERT INTO tasks (task_id, user_id, task_type, status, priority, payload, credits_reserved)
                        VALUES (:tid, :uid, 'video_gen', 'queued', :priority, :payload, :credits)
                    """),
                    {
                        "tid": child_id,
                        "uid": user_id,
                        "priority": priority,
                        "payload": str(item),
                        "credits": 10,
                    },
                )

                celery_app.send_task(
                    "tasks.video.generate",
                    args=[child_id, str(user_id), item],
                    kwargs={"transaction_id": transaction_id},
                    queue="video",
                    priority=priority,
                )

    return BatchTaskSubmitResponse(
        parent_task_id=parent_task_id,
        child_task_ids=child_task_ids,
        status="queued",
        total_credits_reserved=quantity * 10,
    )

# 同理改造 batch_generate_images:
# - check_concurrent_limit
# - check_rate_limit(... "image_gen" ...)
# - reserve_credits(... "image_gen" ...)
# - 派发任务
```

## 验收标准

1. Free 用户连续提交 6 个视频生成 → 第 6 个返回 429 + retry-after
2. Free 用户同时有 2 个 running 任务时再提交 → 返回 429 并发超限
3. 用户积分不足时提交 → 返回 402
4. Pro 用户限流阈值更高（50/h 视频）
5. 429 响应包含 `Retry-After` header
6. 积分预扣成功后 transaction_id 传递给 Celery 任务
7. `GET /api/credits/pricing` 仍然公开无需鉴权

## 完成后

告诉 orchestrator：T8 完成，列出修改/创建的文件清单。
