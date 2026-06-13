# T18 指令 — api-biz 终端

## 你的身份

你是 `api-biz` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 任务目标

实现完整的管理后台 API：Admin 鉴权 + 7 个模块的端点。

## 分支

（如果 git 报错可忽略，直接在当前分支工作）

## 需要创建/修改的文件

### 1. `alembic/versions/002_add_admin_field.py`（新建）

```python
"""add is_admin field to users

Revision ID: 002_add_admin_field
Revises: 001_initial_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "002_add_admin_field"
down_revision = "001_initial_schema"

def upgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))

def downgrade() -> None:
    op.drop_column("users", "is_admin")
```

### 2. `app/middleware/admin.py`（新建）

Admin 鉴权中间件：

```python
"""
Admin 鉴权中间件。
要求用户已登录且 is_admin = True。
"""
from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user


async def require_admin(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """验证当前用户是管理员。非管理员返回 403。"""
    result = await db.execute(
        text("SELECT is_admin FROM users WHERE id = :uid"),
        {"uid": current_user["id"]},
    )
    row = result.fetchone()
    if not row or not row.is_admin:
        raise HTTPException(403, "Admin access required")
    return current_user
```

### 3. `app/routes/admin.py`（新建）

完整的 Admin 路由模块。这是核心文件，包含所有管理端点：

```python
"""
管理后台 API 路由。

所有端点需要 admin 权限。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.admin import require_admin
from app.services.key_pool import key_pool
from app.redis_client import redis_client

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ========== 总览 ==========

@router.get("/overview")
async def admin_overview(db: AsyncSession = Depends(get_db)):
    """管理后台总览数据"""
    # 用户统计
    users_result = await db.execute(text("""
        SELECT
            COUNT(*) AS total_users,
            COUNT(*) FILTER (WHERE status = 'active') AS active_users,
            COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') AS new_today
        FROM users
    """))
    users_stats = users_result.mappings().first()

    # 任务统计
    tasks_result = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE status IN ('queued', 'running')) AS active_tasks,
            COUNT(*) FILTER (WHERE status = 'done' AND completed_at > NOW() - INTERVAL '24 hours') AS completed_today,
            COUNT(*) FILTER (WHERE status IN ('failed', 'dead_letter') AND updated_at > NOW() - INTERVAL '24 hours') AS failed_today
        FROM tasks
    """))
    tasks_stats = tasks_result.mappings().first()

    # 收入统计（今日）
    revenue_result = await db.execute(text("""
        SELECT COALESCE(SUM(ABS(amount)), 0) AS revenue_today
        FROM credit_transactions
        WHERE tx_type = 'charge' AND created_at > NOW() - INTERVAL '24 hours'
    """))
    revenue = revenue_result.scalar()

    # 死信数量
    dead_result = await db.execute(text(
        "SELECT COUNT(*) FROM dead_letter_tasks WHERE resolved = FALSE"
    ))
    dead_count = dead_result.scalar()

    return {
        "users": dict(users_stats),
        "tasks": dict(tasks_stats),
        "revenue_today": revenue,
        "dead_letter_count": dead_count,
    }


# ========== 用户管理 ==========

@router.get("/users")
async def admin_list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tier: str | None = None,
    status: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """用户列表（分页、筛选、搜索）"""
    where_parts = []
    params: dict = {"limit": page_size, "offset": (page - 1) * page_size}

    if tier:
        where_parts.append("u.tier = :tier")
        params["tier"] = tier
    if status:
        where_parts.append("u.status = :status")
        params["status"] = status
    if search:
        where_parts.append("(u.email ILIKE :search OR u.display_name ILIKE :search)")
        params["search"] = f"%{search}%"

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM users u {where_clause}"), params
    )
    total = count_result.scalar()

    result = await db.execute(
        text(f"""
            SELECT u.id, u.user_id, u.email, u.display_name, u.tier, u.status, u.is_admin,
                   u.created_at, ca.balance, ca.lifetime_spent
            FROM users u
            LEFT JOIN credit_accounts ca ON ca.user_id = u.id
            {where_clause}
            ORDER BY u.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().fetchall()

    return {"users": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.patch("/users/{user_id}")
async def admin_update_user(
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """修改用户（tier、status、is_admin）"""
    allowed_fields = {"tier", "status", "is_admin"}
    updates = {k: v for k, v in payload.items() if k in allowed_fields}
    if not updates:
        raise HTTPException(400, "No valid fields to update")

    sets = [f"{k} = :{k}" for k in updates]
    updates["uid"] = user_id

    async with db.begin():
        result = await db.execute(
            text(f"UPDATE users SET {', '.join(sets)}, updated_at = NOW() WHERE id = :uid"),
            updates,
        )
        if result.rowcount == 0:
            raise HTTPException(404, "User not found")

    return {"message": "User updated", "updated_fields": list(updates.keys() - {"uid"})}


# ========== 任务监控 ==========

@router.get("/tasks")
async def admin_list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    task_type: str | None = None,
    user_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """任务列表（管理员可看所有用户）"""
    where_parts = []
    params: dict = {"limit": page_size, "offset": (page - 1) * page_size}

    if status:
        where_parts.append("t.status = :status")
        params["status"] = status
    if task_type:
        where_parts.append("t.task_type = :task_type")
        params["task_type"] = task_type
    if user_id:
        where_parts.append("t.user_id = :user_id")
        params["user_id"] = user_id

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {where_clause}"), params
    )
    total = count_result.scalar()

    result = await db.execute(
        text(f"""
            SELECT t.task_id, t.user_id, t.task_type, t.status, t.priority,
                   t.progress, t.stage_text, t.error_message, t.retry_count,
                   t.credits_reserved, t.credits_charged,
                   t.created_at, t.started_at, t.completed_at,
                   u.email AS user_email
            FROM tasks t
            JOIN users u ON u.id = t.user_id
            {where_clause}
            ORDER BY t.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.mappings().fetchall()

    return {"tasks": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/tasks/stats")
async def admin_task_stats(db: AsyncSession = Depends(get_db)):
    """任务统计：按类型的成功率、平均耗时"""
    result = await db.execute(text("""
        SELECT
            task_type,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'done') AS succeeded,
            COUNT(*) FILTER (WHERE status IN ('failed', 'dead_letter')) AS failed,
            COUNT(*) FILTER (WHERE status IN ('queued', 'running')) AS active,
            ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) FILTER (WHERE completed_at IS NOT NULL AND started_at IS NOT NULL), 1) AS avg_duration_seconds
        FROM tasks
        GROUP BY task_type
        ORDER BY total DESC
    """))
    rows = result.mappings().fetchall()
    return {"stats": [dict(r) for r in rows]}


# ========== 积分与收入 ==========

@router.get("/credits/revenue")
async def admin_revenue(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """收入趋势（按天）"""
    result = await db.execute(
        text("""
            SELECT DATE(created_at) AS date, SUM(ABS(amount)) AS revenue, COUNT(*) AS transactions
            FROM credit_transactions
            WHERE tx_type = 'charge' AND created_at > NOW() - MAKE_INTERVAL(days => :days)
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """),
        {"days": days},
    )
    rows = result.mappings().fetchall()

    # Top 消费者
    top_result = await db.execute(text("""
        SELECT u.id, u.email, u.tier, ca.lifetime_spent, ca.balance
        FROM credit_accounts ca
        JOIN users u ON u.id = ca.user_id
        ORDER BY ca.lifetime_spent DESC
        LIMIT 10
    """))
    top_spenders = top_result.mappings().fetchall()

    return {
        "daily_revenue": [dict(r) for r in rows],
        "top_spenders": [dict(r) for r in top_spenders],
    }


@router.get("/credits/pricing")
async def admin_list_pricing(db: AsyncSession = Depends(get_db)):
    """定价列表"""
    result = await db.execute(text("SELECT * FROM credit_pricing ORDER BY operation"))
    rows = result.mappings().fetchall()
    return {"pricing": [dict(r) for r in rows]}


@router.patch("/credits/pricing/{pricing_id}")
async def admin_update_pricing(
    pricing_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """修改定价"""
    allowed = {"credits_cost", "active"}
    updates = {k: v for k, v in payload.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields")

    sets = [f"{k} = :{k}" for k in updates]
    updates["pid"] = pricing_id

    async with db.begin():
        result = await db.execute(
            text(f"UPDATE credit_pricing SET {', '.join(sets)} WHERE id = :pid"),
            updates,
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Pricing not found")

    return {"message": "Pricing updated"}


# ========== 死信队列 ==========

@router.get("/dead-letter")
async def admin_dead_letter(
    resolved: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """死信任务列表"""
    offset = (page - 1) * page_size
    result = await db.execute(
        text("""
            SELECT dl.id, dl.original_task_id, dl.user_id, dl.task_type,
                   dl.payload, dl.error_history, dl.dead_at, dl.resolved,
                   u.email AS user_email
            FROM dead_letter_tasks dl
            JOIN users u ON u.id = dl.user_id
            WHERE dl.resolved = :resolved
            ORDER BY dl.dead_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"resolved": resolved, "limit": page_size, "offset": offset},
    )
    rows = result.mappings().fetchall()

    count_result = await db.execute(
        text("SELECT COUNT(*) FROM dead_letter_tasks WHERE resolved = :resolved"),
        {"resolved": resolved},
    )
    total = count_result.scalar()

    return {"items": [dict(r) for r in rows], "total": total, "page": page}


@router.post("/dead-letter/{item_id}/retry")
async def admin_retry_dead_letter(item_id: int, db: AsyncSession = Depends(get_db)):
    """重试死信任务（重新入队）"""
    from app.celery_app import celery_app
    import uuid

    async with db.begin():
        result = await db.execute(
            text("SELECT * FROM dead_letter_tasks WHERE id = :id AND resolved = FALSE"),
            {"id": item_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(404, "Dead letter task not found or already resolved")

        # 创建新任务
        new_task_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO tasks (task_id, user_id, task_type, status, priority, payload)
                VALUES (:tid, :uid, :task_type, 'queued', 5, :payload)
            """),
            {
                "tid": new_task_id,
                "uid": row["user_id"],
                "task_type": row["task_type"],
                "payload": row["payload"],
            },
        )

        # 标记已解决
        await db.execute(
            text("UPDATE dead_letter_tasks SET resolved = TRUE WHERE id = :id"),
            {"id": item_id},
        )

    # 派发到对应队列
    task_type_map = {
        "video_gen": ("app.tasks.video_tasks.generate_video_task", "video"),
        "image_gen": ("app.tasks.image_tasks.generate_image_task", "image"),
        "text_gen": ("app.tasks.text_tasks.generate_text_task", "text"),
        "tts": ("app.tasks.tts_tasks.generate_tts_task", "text"),
    }
    task_name, queue = task_type_map.get(row["task_type"], ("app.tasks.text_tasks.generate_text_task", "text"))
    celery_app.send_task(task_name, args=[new_task_id, str(row["user_id"]), row["payload"]], queue=queue)

    return {"message": "Task retried", "new_task_id": new_task_id}


@router.patch("/dead-letter/{item_id}/resolve")
async def admin_resolve_dead_letter(item_id: int, db: AsyncSession = Depends(get_db)):
    """标记死信任务为已解决（不重试）"""
    async with db.begin():
        result = await db.execute(
            text("UPDATE dead_letter_tasks SET resolved = TRUE WHERE id = :id AND resolved = FALSE"),
            {"id": item_id},
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Not found or already resolved")

    return {"message": "Marked as resolved"}


# ========== Key Pool ==========

@router.get("/key-pool")
async def admin_key_pool():
    """Key Pool 实时快照"""
    snapshot = key_pool.snapshot()
    return {"services": snapshot}


# ========== 系统健康 ==========

@router.get("/system")
async def admin_system_health(db: AsyncSession = Depends(get_db)):
    """系统健康状态"""
    # Redis info
    redis_info = await redis_client.info("memory")
    redis_memory = {
        "used_memory_human": redis_info.get("used_memory_human", "unknown"),
        "used_memory_peak_human": redis_info.get("used_memory_peak_human", "unknown"),
    }

    # DB 连接测试
    try:
        await db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception:
        db_status = "unhealthy"

    # 队列深度（从 tasks 表统计）
    queue_result = await db.execute(text("""
        SELECT task_type, COUNT(*) AS depth
        FROM tasks
        WHERE status IN ('queued', 'running')
        GROUP BY task_type
    """))
    queue_depth = {r["task_type"]: r["depth"] for r in queue_result.mappings().fetchall()}

    return {
        "database": db_status,
        "redis": redis_memory,
        "queue_depth": queue_depth,
    }


# ========== 限流配置 ==========

@router.get("/rate-limits")
async def admin_rate_limits(db: AsyncSession = Depends(get_db)):
    """限流配置列表"""
    result = await db.execute(text("SELECT * FROM rate_limit_config ORDER BY tier, resource"))
    rows = result.mappings().fetchall()
    return {"rules": [dict(r) for r in rows]}


@router.patch("/rate-limits/{rule_id}")
async def admin_update_rate_limit(
    rule_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """修改限流规则"""
    allowed = {"window_seconds", "max_count"}
    updates = {k: v for k, v in payload.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields")

    sets = [f"{k} = :{k}" for k in updates]
    updates["rid"] = rule_id

    async with db.begin():
        result = await db.execute(
            text(f"UPDATE rate_limit_config SET {', '.join(sets)} WHERE id = :rid"),
            updates,
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Rule not found")

    return {"message": "Rate limit updated"}
```

### 4. `app/routes/__init__.py` — 注册 admin 路由

```python
from app.routes.admin import router as admin_router

api_router.include_router(admin_router)
```

### 5. `app/middleware/auth.py` — 确保 get_current_user 返回 is_admin

在查询用户信息时，确保 SELECT 包含 `is_admin` 字段，并在返回的 dict 中包含它。如果当前查询没有 is_admin，需要添加。

## 验收标准

1. 非 admin 用户访问 `/api/admin/*` 返回 403
2. `GET /api/admin/overview` 返回用户数、任务数、今日收入、死信数
3. `GET /api/admin/users` 支持分页、按 tier/status 筛选、邮箱搜索
4. `PATCH /api/admin/users/:id` 能修改 tier、status、is_admin
5. `GET /api/admin/tasks` 能看所有用户的任务
6. `GET /api/admin/tasks/stats` 返回按类型的成功率和平均耗时
7. `GET /api/admin/credits/revenue` 返回日收入趋势和 Top 消费者
8. `GET /api/admin/dead-letter` 返回未解决的死信任务
9. `POST /api/admin/dead-letter/:id/retry` 能重新入队
10. `GET /api/admin/key-pool` 返回各 Key 的实时负载
11. `GET /api/admin/system` 返回 DB/Redis 健康状态和队列深度
12. `GET /api/admin/rate-limits` + `PATCH` 能查看和修改限流规则

## 完成后

告诉 orchestrator：T18 完成，列出创建/修改的文件清单，并给出每个端点的响应格式示例（供前端终端使用）。
