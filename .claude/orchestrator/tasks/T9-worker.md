# T9 指令 — worker 终端

## 你的身份

你是 `worker` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 前置条件

Phase 2 已完成：
- `app/services/credits.py` — `credit_service`（charge/refund 方法）
- `app/services/key_pool.py` — `key_pool`（acquire/release/report_error）
- `app/tasks/video_tasks.py` — 已有基础框架
- `app/tasks/image_tasks.py` — 已有基础框架
- `app/tasks/text_tasks.py` — 已有基础框架

T8（api-biz）正在将 `transaction_id` 传递给 Celery 任务的 kwargs。

## 任务目标

完善任务执行逻辑：
1. 任务成功后调用 `credit_service.charge(transaction_id)` 确认扣费
2. 任务失败（超过重试）后调用 `credit_service.refund(transaction_id)` 退还积分
3. 集成 Key Pool 到实际的外部 API 调用流程
4. 完善任务状态回写数据库

## 分支

```bash
git checkout -b worker/phase3-credits-integration
```

## 需要修改的文件

### 1. `app/tasks/video_tasks.py`

完善任务执行，集成积分确认/退还：

```python
@celery_app.task(bind=True, name="tasks.video.generate", max_retries=3)
def generate_video_task(self, task_id: str, user_id: str, payload: dict, transaction_id: str = ""):
    """
    视频生成任务 — 完整流程。

    1. 更新任务状态为 running
    2. 从 Key Pool 获取 key
    3. 调用外部 API
    4. 成功: 更新状态 + charge 积分 + 发布结果
    5. 失败: 重试或退还积分 + 移入死信
    """
    try:
        # 更新状态为 running
        _update_task_status(task_id, status="running", started_at=True)
        _publish_progress(task_id, status="running", progress=0, stage="获取 API Key...")

        # 获取 key
        key_name, api_key = key_pool.acquire(service="seedance")
        try:
            _publish_progress(task_id, status="running", progress=10, stage="提交生成请求...")

            # 调用外部 API（读取 app/services/seedance.py 了解接口）
            # result = call_seedance(api_key, payload)
            # 轮询等待...
            # _publish_progress(task_id, "running", progress, stage)

            # 模拟成功结果（等 seedance.py 就绪后替换）
            result = {"url": "placeholder", "duration": payload.get("duration", 5)}

            # 成功：确认积分扣费
            if transaction_id:
                credit_service.charge(transaction_id)

            # 更新任务状态
            _update_task_status(task_id, status="done", progress=100, result=result)
            _publish_progress(task_id, status="done", progress=100, stage="完成")

            return result

        finally:
            key_pool.release(key_name)

    except key_pool.BackpressureError:
        # 无可用 key，稍后重试（不退积分，还会重试）
        _update_task_status(task_id, status="queued", stage_text="等待可用 Key...")
        raise self.retry(countdown=30)

    except self.MaxRetriesExceededError:
        # 超过最大重试：退还积分 + 移入死信
        if transaction_id:
            credit_service.refund(transaction_id)
        _update_task_status(task_id, status="dead_letter", error_message="Max retries exceeded")
        _move_to_dead_letter(task_id, user_id, "video_gen", payload, "Max retries exceeded")
        _publish_progress(task_id, status="failed", progress=0, stage="任务失败，积分已退还")

    except Exception as exc:
        # 可重试错误
        key_pool.report_error(key_name, type(exc).__name__)
        _update_task_status(task_id, status="queued", retry_count=self.request.retries + 1)
        countdown = [30, 120, 300][min(self.request.retries, 2)]
        raise self.retry(exc=exc, countdown=countdown)
```

### 2. 公共辅助函数（在 `app/tasks/_shared.py` 中添加或完善）

```python
"""
任务公共辅助函数。
"""
import json
from datetime import datetime, timezone

import redis
from sqlalchemy import text

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.services.credits import credit_service
from app.services.key_pool import key_pool

settings = get_settings()
sync_redis = redis.from_url(settings.redis_url, decode_responses=True)


def _publish_progress(task_id: str, status: str, progress: int, stage: str):
    """通过 Redis pub/sub 发布任务进度"""
    sync_redis.publish(
        f"task:{task_id}:progress",
        json.dumps({
            "task_id": task_id,
            "type": "task_update" if status not in ("done", "failed") else f"task_{status}",
            "status": status,
            "progress": progress,
            "stage_text": stage,
        })
    )


def _update_task_status(
    task_id: str,
    status: str | None = None,
    progress: int | None = None,
    stage_text: str | None = None,
    result: dict | None = None,
    error_message: str | None = None,
    retry_count: int | None = None,
    started_at: bool = False,
):
    """同步更新任务状态到数据库"""
    import asyncio

    async def _do():
        async with AsyncSessionLocal() as session:
            async with session.begin():
                sets = ["updated_at = NOW()"]
                params = {"tid": task_id}

                if status:
                    sets.append("status = :status")
                    params["status"] = status
                if progress is not None:
                    sets.append("progress = :progress")
                    params["progress"] = progress
                if stage_text is not None:
                    sets.append("stage_text = :stage_text")
                    params["stage_text"] = stage_text
                if result is not None:
                    sets.append("result = :result")
                    params["result"] = json.dumps(result)
                if error_message is not None:
                    sets.append("error_message = :error_message")
                    params["error_message"] = error_message
                if retry_count is not None:
                    sets.append("retry_count = :retry_count")
                    params["retry_count"] = retry_count
                if started_at:
                    sets.append("started_at = NOW()")
                if status == "done" or status == "failed" or status == "dead_letter":
                    sets.append("completed_at = NOW()")

                await session.execute(
                    text(f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = :tid"),
                    params,
                )

    asyncio.run(_do())


def _move_to_dead_letter(task_id: str, user_id: str, task_type: str, payload: dict, error: str):
    """将任务移入死信表"""
    import asyncio

    async def _do():
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        INSERT INTO dead_letter_tasks (original_task_id, user_id, task_type, payload, error_history)
                        VALUES (:tid, :uid, :task_type, :payload, :errors)
                    """),
                    {
                        "tid": task_id,
                        "uid": int(user_id),
                        "task_type": task_type,
                        "payload": json.dumps(payload),
                        "errors": json.dumps([{"error": error, "at": datetime.now(timezone.utc).isoformat()}]),
                    },
                )

    asyncio.run(_do())
```

### 3. `app/tasks/image_tasks.py` 和 `app/tasks/text_tasks.py`

同样的模式改造：
- 接收 `transaction_id` 参数
- 成功调用 `credit_service.charge(transaction_id)`
- 失败超过重试调用 `credit_service.refund(transaction_id)`
- 使用 `key_pool.acquire("seedream")` / `key_pool.acquire("doubao")`
- 调用 `_update_task_status` 和 `_publish_progress`

## 验收标准

1. 任务成功后 `credit_transactions` 表有 `charge` 类型记录
2. 任务失败超过重试后 `credit_transactions` 表有 `refund` 类型记录
3. 失败任务写入 `dead_letter_tasks` 表
4. 任务执行过程中 `tasks.status` 正确更新（queued → running → done/failed）
5. `tasks.started_at` 和 `tasks.completed_at` 正确写入
6. Redis pub/sub 发布的消息包含正确的 task_id 和进度
7. Key Pool 错误触发冷却机制

## 完成后

告诉 orchestrator：T9 完成，列出修改/创建的文件清单。
