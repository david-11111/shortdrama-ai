# T3 指令 — api-biz 终端

## 你的身份

你是 `api-biz` 终端。先读取 `.claude/team/api-biz.md` 了解你的权限边界。

## 前置条件

T1（devops）和 T2（worker）已完成。以下文件已就绪：
- `app/config.py` — 全局配置
- `app/db.py` — 数据库 session（`get_db`、`AsyncSessionLocal`、`Base`）
- `app/redis_client.py` — Redis 连接（`redis_client`）
- `app/celery_app.py` — Celery 实例（`celery_app`）
- `app/tasks/video_tasks.py` — 视频生成任务（`tasks.video.generate`）
- `app/tasks/image_tasks.py` — 图片生成任务（`tasks.image.generate`）
- `app/tasks/text_tasks.py` — 文本生成任务（`tasks.text.generate`）
- `app/services/credits.py` — 积分服务（`credit_service`）

## 任务目标

改造 `app/main.py`，将现有批量生成端点从同步阻塞（executor.submit）切换为 Celery 异步派发，并新增任务查询端点和 WebSocket 实时推送。

## 分支

```bash
git checkout -b api/phase1-async
```

## 需要创建/修改的文件

### 1. `app/schemas/__init__.py`

```python
from app.schemas.tasks import *  # noqa: F401,F403
```

### 2. `app/schemas/tasks.py`

```python
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class TaskSubmitResponse(BaseModel):
    task_id: str
    status: str = "queued"
    message: str = "Task submitted successfully"

class BatchTaskSubmitResponse(BaseModel):
    parent_task_id: str
    child_task_ids: list[str]
    status: str = "queued"
    total_credits_reserved: int

class TaskStatusResponse(BaseModel):
    task_id: str
    task_type: str
    status: str
    progress: int = 0
    stage_text: Optional[str] = None
    result: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class TaskListResponse(BaseModel):
    tasks: list[TaskStatusResponse]
    total: int
    page: int
    page_size: int

class TaskCancelResponse(BaseModel):
    task_id: str
    status: str
    message: str
```

### 3. `app/routes/__init__.py`

```python
from fastapi import APIRouter
from app.routes.tasks import router as tasks_router

api_router = APIRouter(prefix="/api")
api_router.include_router(tasks_router)
```

### 4. `app/routes/tasks.py`

任务查询和取消端点：

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db import get_db
from app.schemas.tasks import TaskStatusResponse, TaskListResponse, TaskCancelResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get("", response_model=TaskListResponse)
async def list_tasks(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    # TODO Phase 2: user_id from auth middleware
):
    """查询任务列表（分页）"""
    offset = (page - 1) * page_size

    # 构建查询
    where_clause = ""
    params = {"limit": page_size, "offset": offset}

    if status:
        where_clause = "WHERE status = :status"
        params["status"] = status

    # 查总数
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM tasks {where_clause}"), params
    )
    total = count_result.scalar()

    # 查数据
    result = await db.execute(
        text(f"""
            SELECT task_id, task_type, status, progress, stage_text,
                   result, error_message, created_at, started_at, completed_at
            FROM tasks {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params
    )
    rows = result.fetchall()

    tasks = [
        TaskStatusResponse(
            task_id=str(row.task_id),
            task_type=row.task_type,
            status=row.status,
            progress=row.progress,
            stage_text=row.stage_text,
            result=row.result,
            error_message=row.error_message,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )
        for row in rows
    ]

    return TaskListResponse(tasks=tasks, total=total, page=page, page_size=page_size)


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """查询单个任务状态"""
    result = await db.execute(
        text("""
            SELECT task_id, task_type, status, progress, stage_text,
                   result, error_message, created_at, started_at, completed_at
            FROM tasks WHERE task_id = :tid
        """),
        {"tid": task_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(404, "Task not found")

    return TaskStatusResponse(
        task_id=str(row.task_id),
        task_type=row.task_type,
        status=row.status,
        progress=row.progress,
        stage_text=row.stage_text,
        result=row.result,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


@router.post("/{task_id}/cancel", response_model=TaskCancelResponse)
async def cancel_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """取消任务（仅 pending/queued 状态可取消）"""
    async with db.begin():
        result = await db.execute(
            text("SELECT status, credits_reserved FROM tasks WHERE task_id = :tid FOR UPDATE"),
            {"tid": task_id}
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(404, "Task not found")

        if row.status not in ("pending", "queued"):
            raise HTTPException(400, f"Cannot cancel task in '{row.status}' status")

        await db.execute(
            text("UPDATE tasks SET status = 'cancelled', updated_at = NOW() WHERE task_id = :tid"),
            {"tid": task_id}
        )

        # TODO: 退还预扣积分 (credit_service.refund)

    return TaskCancelResponse(task_id=task_id, status="cancelled", message="Task cancelled")
```

### 5. `app/main.py` 改造

在现有 `app/main.py` 中做以下改造（保留现有端点路径不变）：

**核心改动：**
- 导入 `celery_app` 和路由
- 批量生成端点改为异步派发（返回 202 + task_id）
- 注册路由和 WebSocket

```python
# 在 main.py 顶部新增导入
from app.celery_app import celery_app
from app.routes import api_router
from app.db import get_db, AsyncSessionLocal
from app.schemas.tasks import BatchTaskSubmitResponse
from sqlalchemy import text
import uuid

# 注册路由
app.include_router(api_router)

# 改造批量生成视频端点（保留原路径）
@app.post("/api/batch/generate-videos", status_code=202, response_model=BatchTaskSubmitResponse)
async def batch_generate_videos(payload: BatchGenerateVideosRequest):
    """
    改造后：异步派发到 Celery，立即返回 task_id。
    客户端通过 WebSocket 或轮询 GET /api/tasks/{id} 获取进度。
    """
    parent_task_id = str(uuid.uuid4())
    child_task_ids = []

    async with AsyncSessionLocal() as session:
        async with session.begin():
            for item in payload.items:
                child_id = str(uuid.uuid4())
                child_task_ids.append(child_id)

                # 写入 tasks 表
                await session.execute(
                    text("""
                        INSERT INTO tasks (task_id, user_id, task_type, status, priority, payload, credits_reserved)
                        VALUES (:tid, :uid, 'video_gen', 'queued', 5, :payload, :credits)
                    """),
                    {
                        "tid": child_id,
                        "uid": 1,  # TODO Phase 2: from auth middleware
                        "payload": item.model_dump_json() if hasattr(item, 'model_dump_json') else "{}",
                        "credits": 10,  # TODO: 按 duration 查定价
                    }
                )

                # 派发 Celery 任务
                celery_app.send_task(
                    "tasks.video.generate",
                    args=[child_id, "1", item.dict() if hasattr(item, 'dict') else {}],
                    queue="video",
                    priority=5,
                )

    return BatchTaskSubmitResponse(
        parent_task_id=parent_task_id,
        child_task_ids=child_task_ids,
        status="queued",
        total_credits_reserved=len(child_task_ids) * 10,
    )

# 同理改造 batch_generate_images（结构相同，queue="image"，任务名="tasks.image.generate"）
```

### 6. `app/ws/__init__.py`

```python
```

### 7. `app/ws/task_updates.py`

WebSocket 实时推送（基础版）：

```python
import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect
from app.redis_client import redis_client

async def ws_task_updates(websocket: WebSocket):
    """
    WebSocket 端点：实时推送任务进度。

    客户端连接后发送 subscribe 消息指定要监听的 task_id 列表。
    服务端通过 Redis pub/sub 接收进度更新并转发给客户端。
    """
    await websocket.accept()

    subscribed_tasks: set[str] = set()
    pubsub = redis_client.pubsub()

    try:
        while True:
            # 非阻塞接收客户端消息
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

            # 检查 Redis pub/sub 消息
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                await websocket.send_text(message["data"])

    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.close()
```

在 `app/main.py` 中注册 WebSocket：

```python
from app.ws.task_updates import ws_task_updates

@app.websocket("/ws/tasks")
async def websocket_endpoint(websocket: WebSocket):
    await ws_task_updates(websocket)
```

## 验收标准

1. `POST /api/batch/generate-videos` 返回 202 + task_id 列表（不再阻塞等待）
2. `GET /api/tasks` 能分页查询任务列表
3. `GET /api/tasks/{task_id}` 能查询单个任务状态
4. `POST /api/tasks/{task_id}/cancel` 能取消 pending 任务
5. `WS /ws/tasks` 能连接，subscribe 后能收到进度推送
6. 现有其他端点不受影响

## 注意事项

- `app/main.py` 是改造而非重写，保留现有端点，只改批量生成相关的
- Phase 1 暂时硬编码 `user_id=1`，Phase 2 由 api-auth 加鉴权后注入
- 如果现有 `app/main.py` 结构不明确，先读取了解再改造

## 完成后

告诉 orchestrator：T3 完成，列出创建/修改的文件清单。
