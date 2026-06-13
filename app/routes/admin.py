"""
管理后台 API 路由。

所有端点需要 admin 权限。
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.admin import require_admin
from app.redis_client import redis_client
from app.services.cost_guard import get_cost_guard_status
from app.services.key_pool import key_pool

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


@router.get("/cost-guard")
async def admin_cost_guard(user_id: int | None = None, db: AsyncSession = Depends(get_db)):
    return await get_cost_guard_status(db, user_id=user_id)


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
        # Escape LIKE wildcards in user input
        safe_search = search.replace("%", "\\%").replace("_", "\\_")
        params["search"] = f"%{safe_search}%"

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
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """修改用户（tier、status、is_admin）"""
    allowed_fields = {"tier", "status", "is_admin"}
    updates = {k: v for k, v in payload.items() if k in allowed_fields}
    if not updates:
        raise HTTPException(400, "No valid fields to update")

    # 防止 admin 修改自己的权限或禁用自己
    if hasattr(request, "state") and hasattr(request.state, "user"):
        current_admin_id = getattr(request.state, "user", {}).get("id")
        if current_admin_id == user_id:
            if "is_admin" in updates or ("status" in updates and updates["status"] != "active"):
                raise HTTPException(400, "Cannot modify your own admin status or disable yourself")

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


@router.get("/provider-costs")
async def admin_provider_costs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    service: str | None = None,
    user_id: int | None = None,
    match_status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    where_parts = []
    params: dict = {"limit": page_size, "offset": (page - 1) * page_size}
    if service:
        where_parts.append("puc.service = :service")
        params["service"] = service
    if user_id:
        where_parts.append("puc.user_id = :user_id")
        params["user_id"] = user_id
    if match_status:
        where_parts.append("puc.match_status = :match_status")
        params["match_status"] = match_status
    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    total_result = await db.execute(text(f"SELECT COUNT(*) FROM provider_usage_costs puc {where_clause}"), params)
    total = total_result.scalar()
    rows_result = await db.execute(
        text(f"""
            SELECT puc.*, u.email AS user_email
            FROM provider_usage_costs puc
            LEFT JOIN users u ON u.id = puc.user_id
            {where_clause}
            ORDER BY puc.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    summary_result = await db.execute(
        text(f"""
            SELECT
                COUNT(*) AS rows,
                COALESCE(SUM(estimated_cost_yuan), 0) AS estimated_cost_yuan,
                COALESCE(SUM(actual_cost_yuan), 0) AS actual_cost_yuan,
                COALESCE(SUM(credits_charged), 0) AS credits_charged
            FROM provider_usage_costs puc
            {where_clause}
        """),
        params,
    )
    return {
        "items": [dict(r) for r in rows_result.mappings().fetchall()],
        "summary": dict(summary_result.mappings().first()),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/provider-pricing")
async def admin_provider_pricing(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM provider_pricing_rules ORDER BY provider, service, model, effective_at DESC")
    )
    return {"items": [dict(r) for r in result.mappings().fetchall()]}


@router.post("/provider-pricing")
async def admin_create_provider_pricing(payload: dict, db: AsyncSession = Depends(get_db)):
    required = {"provider", "service", "billing_basis", "unit_prices"}
    missing = [key for key in required if key not in payload]
    if missing:
        raise HTTPException(400, f"Missing fields: {', '.join(missing)}")
    async with db.begin():
        result = await db.execute(
            text(
                """
                INSERT INTO provider_pricing_rules (
                    provider, service, model, billing_basis, unit_prices, currency, source, active
                )
                VALUES (
                    :provider, :service, :model, :billing_basis, CAST(:unit_prices AS JSONB),
                    :currency, :source, :active
                )
                RETURNING *
                """
            ),
            {
                "provider": payload["provider"],
                "service": payload["service"],
                "model": payload.get("model", "*"),
                "billing_basis": payload["billing_basis"],
                "unit_prices": json.dumps(payload["unit_prices"], ensure_ascii=False),
                "currency": payload.get("currency", "CNY"),
                "source": payload.get("source"),
                "active": bool(payload.get("active", False)),
            },
        )
        row = result.mappings().first()
    return dict(row)


# ========== 死信队列 ==========

@router.get("/volc-billing")
async def admin_volc_billing(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    trade_type: str | None = None,
    match_status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    where_parts = []
    params: dict = {"limit": page_size, "offset": (page - 1) * page_size}
    if trade_type:
        where_parts.append("trade_type = :trade_type")
        params["trade_type"] = trade_type
    if match_status:
        where_parts.append("match_status = :match_status")
        params["match_status"] = match_status
    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    total_result = await db.execute(text(f"SELECT COUNT(*) FROM volc_billing_rows {where_clause}"), params)
    rows_result = await db.execute(
        text(f"""
            SELECT *
            FROM volc_billing_rows
            {where_clause}
            ORDER BY trade_time DESC NULLS LAST, id DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    summary_result = await db.execute(
        text(f"""
            SELECT
                COUNT(*) AS rows,
                COALESCE(SUM(CASE WHEN amount_yuan < 0 THEN -amount_yuan ELSE 0 END), 0) AS consume_yuan,
                COALESCE(SUM(CASE WHEN amount_yuan > 0 THEN amount_yuan ELSE 0 END), 0) AS recharge_yuan,
                COALESCE(SUM(amount_yuan), 0) AS net_yuan
            FROM volc_billing_rows
            {where_clause}
        """),
        params,
    )
    return {
        "items": [dict(r) for r in rows_result.mappings().fetchall()],
        "summary": dict(summary_result.mappings().first()),
        "total": total_result.scalar(),
        "page": page,
        "page_size": page_size,
    }


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

        await db.execute(
            text("UPDATE dead_letter_tasks SET resolved = TRUE WHERE id = :id"),
            {"id": item_id},
        )

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
