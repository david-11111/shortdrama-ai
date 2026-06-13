# T2 指令 — worker 终端

## 你的身份

你是 `worker` 终端。先读取 `.claude/team/worker.md` 了解你的权限边界。

## 前置条件

T1（devops）已完成。以下文件已就绪：
- `app/config.py` — 配置（含 `ark_api_key_list`、`celery_broker_url` 等）
- `app/db.py` — 数据库 session（`get_db`、`AsyncSessionLocal`）
- `app/redis_client.py` — Redis 连接（`redis_client`）

## 任务目标

实现 Celery 任务框架 + Key Pool + 积分服务 + 三类任务定义。

## 分支

```bash
git checkout -b worker/phase1-celery
```

## 需要创建的文件

### 1. `app/celery_app.py`

```python
from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery("saas_worker")

celery_app.config_from_object({
    "broker_url": settings.celery_broker_url,
    "result_backend": settings.celery_result_backend,
    "task_routes": {
        "app.tasks.video_tasks.*": {"queue": "video"},
        "app.tasks.image_tasks.*": {"queue": "image"},
        "app.tasks.text_tasks.*": {"queue": "text"},
    },
    "worker_prefetch_multiplier": 1,
    "task_acks_late": True,
    "task_reject_on_worker_lost": True,
    "task_time_limit": 900,
    "task_soft_time_limit": 600,
    "broker_transport_options": {
        "priority_steps": list(range(10)),
        "queue_order_strategy": "priority",
    },
    "task_serializer": "json",
    "result_serializer": "json",
    "accept_content": ["json"],
})

celery_app.autodiscover_tasks(["app.tasks"])
```

### 2. `app/worker.py`

Worker 启动入口，确保正确初始化：

```python
"""
启动命令:
  celery -A app.celery_app worker -Q video -c 4 --pool=threads -l info
  celery -A app.celery_app worker -Q image -c 10 --pool=threads -l info
  celery -A app.celery_app worker -Q text -c 20 --pool=threads -l info
"""
from app.celery_app import celery_app  # noqa: F401
```

### 3. `app/tasks/__init__.py`

```python
from app.tasks.video_tasks import *  # noqa: F401,F403
from app.tasks.image_tasks import *  # noqa: F401,F403
from app.tasks.text_tasks import *   # noqa: F401,F403
```

### 4. `app/tasks/video_tasks.py`

实现视频生成任务：

```python
import redis
from app.celery_app import celery_app
from app.services.key_pool import key_pool
from app.config import get_settings

settings = get_settings()
sync_redis = redis.from_url(settings.redis_url, decode_responses=True)

@celery_app.task(bind=True, name="tasks.video.generate", max_retries=3)
def generate_video_task(self, task_id: str, user_id: str, payload: dict):
    """
    视频生成任务。

    payload 包含:
      - prompt: str
      - duration: int (5/8/10)
      - model: str (可选)
      - 其他 seedance 参数

    流程:
      1. 从 Key Pool 获取 key
      2. 调用 Seedance API 提交生成
      3. 轮询等待结果
      4. 上报进度（通过 Redis pub/sub）
      5. 成功：发布结果 + 更新任务状态
      6. 失败：根据错误类型决定重试或放弃
    """
    try:
        # 上报开始
        _publish_progress(task_id, status="running", progress=0, stage="获取 API Key...")

        key_name, api_key = key_pool.acquire(service="seedance")
        try:
            _publish_progress(task_id, status="running", progress=10, stage="提交生成请求...")

            # TODO: 调用 seedance API（读取 app/services/seedance.py 了解接口）
            # submit_result = call_seedance_submit(api_key, payload)
            # task_external_id = submit_result["task_id"]

            # TODO: 轮询等待
            # while not done:
            #     status = poll_seedance(api_key, task_external_id)
            #     _publish_progress(task_id, "running", progress, stage)

            # 成功
            result = {"url": "placeholder", "duration": payload.get("duration", 5)}
            _publish_progress(task_id, status="done", progress=100, stage="完成")
            return result

        finally:
            key_pool.release(key_name)

    except key_pool.BackpressureError:
        # 无可用 key，稍后重试
        raise self.retry(countdown=30)
    except Exception as exc:
        key_pool.report_error(key_name, type(exc).__name__)
        # 指数退避重试: 30s, 120s, 300s
        countdown = [30, 120, 300][self.request.retries]
        raise self.retry(exc=exc, countdown=countdown)


def _publish_progress(task_id: str, status: str, progress: int, stage: str):
    """通过 Redis pub/sub 发布任务进度"""
    import json
    sync_redis.publish(
        f"task:{task_id}:progress",
        json.dumps({
            "task_id": task_id,
            "status": status,
            "progress": progress,
            "stage_text": stage,
        })
    )
```

### 5. `app/tasks/image_tasks.py`

与 video_tasks 结构相同，但：
- 任务名：`tasks.image.generate`
- 调用 Seedream API
- 无需轮询（同步返回）
- 重试间隔更短：10s, 30s, 60s

### 6. `app/tasks/text_tasks.py`

与 video_tasks 结构相同，但：
- 任务名：`tasks.text.generate`
- 调用 Doubao API
- 同步返回
- 重试间隔：5s, 15s, 30s

### 7. `app/services/key_pool.py`

完整实现 Key Pool 管理器：

```python
import redis
import time
from app.config import get_settings

settings = get_settings()

class BackpressureError(Exception):
    """所有 key 都不可用"""
    pass

class KeyPool:
    """
    管理平台持有的多把 ARK API key。

    Redis 原子计数器跟踪每把 key 的状态:
      ark_key:{name}:load     → 当前并发数 (INCR/DECR)
      ark_key:{name}:cooldown → 冷却标记 (SET + TTL)
      ark_key:{name}:rpm      → 本分钟请求数 (INCR + EXPIRE 60s)
    """

    BackpressureError = BackpressureError

    def __init__(self):
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        self._keys = settings.ark_api_key_list  # ["key1", "key2", ...]

    def acquire(self, service: str, concurrency_limit: int = 2) -> tuple[str, str]:
        """
        获取负载最低的可用 key。

        Args:
            service: 服务类型 (seedance/seedream/doubao)
            concurrency_limit: 单 key 并发上限

        Returns:
            (key_name, api_key) 元组

        Raises:
            BackpressureError: 无可用 key
        """
        # 按服务类型设置并发上限
        limits = {"seedance": 2, "seedream": 5, "doubao": 10}
        limit = limits.get(service, concurrency_limit)

        # 找负载最低的可用 key
        best_key = None
        best_load = float("inf")

        for i, api_key in enumerate(self._keys):
            key_name = f"key_{i}"

            # 检查冷却
            if self._redis.exists(f"ark_key:{key_name}:cooldown"):
                continue

            # 检查负载
            load = int(self._redis.get(f"ark_key:{key_name}:load") or 0)
            if load < limit and load < best_load:
                best_key = (key_name, api_key)
                best_load = load

        if best_key is None:
            raise BackpressureError(f"No available key for service: {service}")

        key_name, api_key = best_key
        # 原子递增负载
        self._redis.incr(f"ark_key:{key_name}:load")
        # 递增 RPM 计数
        rpm_key = f"ark_key:{key_name}:rpm"
        self._redis.incr(rpm_key)
        self._redis.expire(rpm_key, 60)

        return key_name, api_key

    def release(self, key_name: str):
        """请求完成后释放（DECR load，最小为0）"""
        load_key = f"ark_key:{key_name}:load"
        new_val = self._redis.decr(load_key)
        if new_val < 0:
            self._redis.set(load_key, 0)

    def report_error(self, key_name: str, error_type: str):
        """
        报告错误，触发冷却。
        - 429 (RateLimitError) → 冷却 60s
        - 500 (ServerError) → 冷却 30s
        - 连续 3 次错误 → 冷却 300s
        """
        error_count_key = f"ark_key:{key_name}:errors"
        count = self._redis.incr(error_count_key)
        self._redis.expire(error_count_key, 300)

        if count >= 3:
            cooldown = 300
        elif "429" in error_type or "RateLimit" in error_type:
            cooldown = 60
        else:
            cooldown = 30

        self._redis.setex(f"ark_key:{key_name}:cooldown", cooldown, "1")


# 全局单例
key_pool = KeyPool()
```

### 8. `app/services/credits.py`

积分服务实现：

```python
from sqlalchemy import text
from app.db import AsyncSessionLocal

class InsufficientCreditsError(Exception):
    pass

class CreditService:
    """
    积分服务 — 预扣模式。

    流程: reserve → (任务执行) → charge 或 refund
    """

    async def check_balance(self, user_id: int, operation: str, quantity: int = 1) -> bool:
        """检查余额是否足够"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": user_id}
            )
            row = result.fetchone()
            if not row:
                return False

            # 查定价
            pricing = await session.execute(
                text("SELECT credits_cost FROM credit_pricing WHERE operation = :op AND active = true"),
                {"op": operation}
            )
            price_row = pricing.fetchone()
            if not price_row:
                return False

            return row.balance >= price_row.credits_cost * quantity

    async def reserve(self, user_id: int, operation: str, quantity: int = 1) -> str:
        """
        预扣积分，返回 transaction_id。
        使用 SELECT FOR UPDATE 锁行保证原子性。
        """
        async with AsyncSessionLocal() as session:
            async with session.begin():
                # 查定价
                pricing = await session.execute(
                    text("SELECT credits_cost FROM credit_pricing WHERE operation = :op AND active = true"),
                    {"op": operation}
                )
                price_row = pricing.fetchone()
                if not price_row:
                    raise ValueError(f"Unknown operation: {operation}")

                total_cost = price_row.credits_cost * quantity

                # 锁行检查余额
                account = await session.execute(
                    text("SELECT balance FROM credit_accounts WHERE user_id = :uid FOR UPDATE"),
                    {"uid": user_id}
                )
                acc_row = account.fetchone()
                if not acc_row or acc_row.balance < total_cost:
                    raise InsufficientCreditsError(
                        f"Insufficient credits: need {total_cost}, have {acc_row.balance if acc_row else 0}"
                    )

                # 扣减余额
                await session.execute(
                    text("UPDATE credit_accounts SET balance = balance - :cost, updated_at = NOW() WHERE user_id = :uid"),
                    {"cost": total_cost, "uid": user_id}
                )

                # 写流水
                result = await session.execute(
                    text("""
                        INSERT INTO credit_transactions (user_id, amount, balance_after, tx_type, description)
                        VALUES (:uid, :amount, (SELECT balance FROM credit_accounts WHERE user_id = :uid), 'reserve', :desc)
                        RETURNING id
                    """),
                    {"uid": user_id, "amount": -total_cost, "desc": f"Reserve for {operation} x{quantity}"}
                )
                tx_id = result.fetchone().id

                return str(tx_id)

    async def charge(self, transaction_id: str, actual_amount: int | None = None):
        """确认扣费。如果实际金额小于预扣，退还差额。"""
        async with AsyncSessionLocal() as session:
            async with session.begin():
                tx = await session.execute(
                    text("SELECT user_id, amount FROM credit_transactions WHERE id = :tid"),
                    {"tid": int(transaction_id)}
                )
                tx_row = tx.fetchone()
                if not tx_row:
                    raise ValueError(f"Transaction not found: {transaction_id}")

                reserved = abs(tx_row.amount)
                if actual_amount is not None and actual_amount < reserved:
                    refund = reserved - actual_amount
                    await session.execute(
                        text("UPDATE credit_accounts SET balance = balance + :refund, updated_at = NOW() WHERE user_id = :uid"),
                        {"refund": refund, "uid": tx_row.user_id}
                    )
                    await session.execute(
                        text("""
                            INSERT INTO credit_transactions (user_id, amount, balance_after, tx_type, reference_id, description)
                            VALUES (:uid, :amount, (SELECT balance FROM credit_accounts WHERE user_id = :uid), 'refund_partial', :ref, 'Partial refund')
                        """),
                        {"uid": tx_row.user_id, "amount": refund, "ref": transaction_id}
                    )

    async def refund(self, transaction_id: str):
        """全额退还预扣积分（任务失败时调用）"""
        async with AsyncSessionLocal() as session:
            async with session.begin():
                tx = await session.execute(
                    text("SELECT user_id, amount FROM credit_transactions WHERE id = :tid"),
                    {"tid": int(transaction_id)}
                )
                tx_row = tx.fetchone()
                if not tx_row:
                    return

                refund_amount = abs(tx_row.amount)
                await session.execute(
                    text("UPDATE credit_accounts SET balance = balance + :refund, updated_at = NOW() WHERE user_id = :uid"),
                    {"refund": refund_amount, "uid": tx_row.user_id}
                )
                await session.execute(
                    text("""
                        INSERT INTO credit_transactions (user_id, amount, balance_after, tx_type, reference_id, description)
                        VALUES (:uid, :amount, (SELECT balance FROM credit_accounts WHERE user_id = :uid), 'refund', :ref, 'Task failed refund')
                    """),
                    {"uid": tx_row.user_id, "amount": refund_amount, "ref": transaction_id}
                )


# 全局单例
credit_service = CreditService()
```

## 验收标准

1. `from app.celery_app import celery_app` 正常工作
2. `celery -A app.celery_app inspect registered` 能看到三类任务
3. Key Pool 的 acquire/release/report_error 逻辑正确
4. CreditService 的 reserve/charge/refund 原子性正确
5. 任务进度通过 Redis pub/sub 发布

## 完成后

告诉 orchestrator：T2 完成，列出创建的文件清单和任何需要确认的设计决策。
