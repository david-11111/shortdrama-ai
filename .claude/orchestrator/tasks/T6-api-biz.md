# T6 指令 — api-biz 终端

## 你的身份

你是 `api-biz` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

先读取 `D:/20240313整理文件/Desktop/saas/.claude/team/api-biz.md` 了解你的权限边界。

## 前置条件

T4（api-auth）已完成，以下文件已就绪：
- `app/middleware/auth.py` — 导出 `get_current_user` 依赖注入
- `app/middleware/permissions.py` — 导出 `require_tier()` 权限校验
- `app/services/auth.py` — JWT 签发/验证
- `app/services/users.py` — 用户 CRUD

`get_current_user` 返回的 dict 结构：
```python
{
    "id": int,           # 数据库主键（用于 WHERE user_id = ?）
    "user_id": UUID,     # 外部 UUID
    "email": str,
    "display_name": str | None,
    "tier": str,         # "free" | "pro" | "enterprise"
    "status": str,       # "active"
    "created_at": datetime,
}
```

## 任务目标

将现有端点加上鉴权和数据隔离。所有业务端点必须：
1. 依赖 `get_current_user` 获取当前用户
2. 数据库操作加 `WHERE user_id = :uid` 过滤
3. 创建数据时写入 `user_id`

## 分支

```bash
git checkout -b api/phase2-user-isolation
```

## 需要修改的文件

### 1. `app/main.py`

改造批量生成端点，加入鉴权和 user_id：

```python
from fastapi import Depends
from app.middleware.auth import get_current_user

@app.post("/api/batch/generate-videos", status_code=202, response_model=BatchTaskSubmitResponse)
async def batch_generate_videos(payload: dict, current_user: dict = Depends(get_current_user)):
    """加入鉴权，user_id 从 current_user 获取"""
    items = payload.get("items", [])
    parent_task_id = str(uuid.uuid4())
    child_task_ids = []
    user_id = current_user["id"]
    user_tier = current_user["tier"]

    # 根据 tier 设置优先级
    priority_map = {"free": 5, "pro": 3, "enterprise": 1}
    priority = priority_map.get(user_tier, 5)

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
                    queue="video",
                    priority=priority,
                )

    return BatchTaskSubmitResponse(
        parent_task_id=parent_task_id,
        child_task_ids=child_task_ids,
        status="queued",
        total_credits_reserved=len(child_task_ids) * 10,
    )

# 同理改造 batch_generate_images
```

### 2. `app/routes/tasks.py`

所有端点加入鉴权 + user_id 过滤：

```python
from app.middleware.auth import get_current_user

@router.get("", response_model=TaskListResponse)
async def list_tasks(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),  # 新增
):
    """查询当前用户的任务列表"""
    offset = (page - 1) * page_size
    user_id = current_user["id"]

    where_clause = "WHERE user_id = :user_id"
    params: dict = {"limit": page_size, "offset": offset, "user_id": user_id}

    if status:
        where_clause += " AND status = :status"
        params["status"] = status

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM tasks {where_clause}"), params
    )
    total = count_result.scalar()

    result = await db.execute(
        text(f"""
            SELECT task_id, task_type, status, progress, stage_text,
                   result, error_message, created_at, started_at, completed_at
            FROM tasks {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.fetchall()
    # ... 同之前的序列化逻辑


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),  # 新增
):
    """查询单个任务（只能查自己的）"""
    result = await db.execute(
        text("""
            SELECT task_id, task_type, status, progress, stage_text,
                   result, error_message, created_at, started_at, completed_at
            FROM tasks WHERE task_id = :tid AND user_id = :uid
        """),
        {"tid": task_id, "uid": current_user["id"]},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(404, "Task not found")
    # ...


@router.post("/{task_id}/cancel", response_model=TaskCancelResponse)
async def cancel_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),  # 新增
):
    """取消任务（只能取消自己的）"""
    async with db.begin():
        result = await db.execute(
            text("SELECT status, credits_reserved FROM tasks WHERE task_id = :tid AND user_id = :uid FOR UPDATE"),
            {"tid": task_id, "uid": current_user["id"]},
        )
        # ...
```

### 3. `app/routes/credits.py`（新建）

积分查询端点：

```python
"""
积分路由：查询余额、交易历史、定价表。

端点:
  GET /api/credits          → 当前余额
  GET /api/credits/transactions → 交易历史
  GET /api/credits/pricing  → 操作定价表
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user

router = APIRouter(prefix="/credits", tags=["credits"])

@router.get("")
async def get_credits(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查询当前用户积分余额"""
    result = await db.execute(
        text("SELECT balance, lifetime_earned, lifetime_spent FROM credit_accounts WHERE user_id = :uid"),
        {"uid": current_user["id"]},
    )
    row = result.mappings().fetchone()
    if not row:
        return {"balance": 0, "lifetime_earned": 0, "lifetime_spent": 0}
    return dict(row)

@router.get("/transactions")
async def get_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查询积分交易历史"""
    offset = (page - 1) * page_size
    result = await db.execute(
        text("""
            SELECT amount, balance_after, tx_type, reference_id, description, created_at
            FROM credit_transactions
            WHERE user_id = :uid
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"uid": current_user["id"], "limit": page_size, "offset": offset},
    )
    rows = result.mappings().fetchall()
    return {"transactions": [dict(r) for r in rows], "page": page, "page_size": page_size}

@router.get("/pricing")
async def get_pricing(db: AsyncSession = Depends(get_db)):
    """查询操作定价表（公开，无需鉴权）"""
    result = await db.execute(
        text("SELECT operation, credits_cost, tier_overrides FROM credit_pricing WHERE active = TRUE")
    )
    rows = result.mappings().fetchall()
    return {"pricing": [dict(r) for r in rows]}
```

### 4. `app/routes/__init__.py`

注册 credits 路由：

```python
from fastapi import APIRouter

from app.routes.tasks import router as tasks_router
from app.routes.auth import router as auth_router
from app.routes.users import router as users_router
from app.routes.credits import router as credits_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(tasks_router)
api_router.include_router(credits_router)
```

### 5. `app/schemas/credits.py`（新建）

```python
from pydantic import BaseModel
from datetime import datetime

class CreditBalanceResponse(BaseModel):
    balance: int
    lifetime_earned: int
    lifetime_spent: int

class CreditTransaction(BaseModel):
    amount: int
    balance_after: int
    tx_type: str
    reference_id: str | None
    description: str | None
    created_at: datetime

class CreditTransactionsResponse(BaseModel):
    transactions: list[CreditTransaction]
    page: int
    page_size: int

class CreditPricing(BaseModel):
    operation: str
    credits_cost: int
    tier_overrides: dict | None

class CreditPricingResponse(BaseModel):
    pricing: list[CreditPricing]
```

### 6. `app/ws/task_updates.py` 改造

WebSocket 连接加入 Token 验证：

```python
import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect, Query
from jose import JWTError

from app.redis_client import redis_client
from app.services.auth import decode_token


async def ws_task_updates(websocket: WebSocket, token: str = Query(default="")):
    """
    WebSocket 端点 — 带 Token 验证。
    连接: WS /ws/tasks?token=<jwt>
    """
    # 验证 Token
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=4001, reason="Invalid token type")
            return
        user_id = int(payload["sub"])
    except (JWTError, Exception):
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await websocket.accept()

    subscribed_tasks: set[str] = set()
    pubsub = redis_client.pubsub()

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                msg = json.loads(data)

                if msg.get("type") == "subscribe":
                    task_ids = msg.get("task_ids", [])
                    for tid in task_ids:
                        if tid not in subscribed_tasks:
                            await pubsub.subscribe(f"task:{tid}:progress")
                            subscribed_tasks.add(tid)

                elif msg.get("type") == "unsubscribe":
                    task_ids = msg.get("task_ids", [])
                    for tid in task_ids:
                        if tid in subscribed_tasks:
                            await pubsub.unsubscribe(f"task:{tid}:progress")
                            subscribed_tasks.discard(tid)

                elif msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

            except asyncio.TimeoutError:
                pass

            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                await websocket.send_text(message["data"])

    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.close()
```

同时修改 `app/main.py` 中的 WebSocket 注册：

```python
@app.websocket("/ws/tasks")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(default="")):
    await ws_task_updates(websocket, token)
```

## 验收标准

1. 所有业务端点需要 Bearer Token 才能访问（无 Token 返回 401）
2. `GET /api/tasks` 只返回当前用户的任务
3. `GET /api/tasks/{id}` 不能查看其他用户的任务（返回 404）
4. `POST /api/tasks/{id}/cancel` 不能取消其他用户的任务
5. `POST /api/batch/generate-videos` 创建的任务 user_id 为当前用户
6. 任务优先级根据用户 tier 设置（free=5, pro=3, enterprise=1）
7. `GET /api/credits` 返回当前用户积分余额
8. `GET /api/credits/transactions` 返回当前用户交易历史
9. `GET /api/credits/pricing` 公开接口，无需鉴权
10. WebSocket 连接需要 token 参数验证

## 完成后

告诉 orchestrator：T6 完成，列出修改/创建的文件清单。
