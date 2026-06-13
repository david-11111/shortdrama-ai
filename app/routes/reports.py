"""用量报表路由"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.middleware.auth import get_current_user

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/usage")
async def get_usage_report(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    days: int = Query(30, ge=1, le=365),
    user=Depends(get_current_user),
):
    """用户用量报表：按天统计各类型任务数和积分消耗"""
    offset = (page - 1) * page_size
    async with AsyncSessionLocal() as session:
        count_result = await session.execute(
            text("""
                SELECT COUNT(*) FROM (
                    SELECT DATE(created_at), task_type
                    FROM tasks
                    WHERE user_id = :user_id
                      AND created_at > NOW() - MAKE_INTERVAL(days => :days)
                    GROUP BY DATE(created_at), task_type
                ) sub
            """),
            {"user_id": user["id"], "days": days},
        )
        total = count_result.scalar() or 0

        result = await session.execute(
            text("""
                SELECT DATE(created_at) AS date,
                       task_type,
                       COUNT(*) AS task_count,
                       COUNT(*) FILTER (WHERE status = 'done') AS success_count,
                       COALESCE(SUM(credits_charged), 0) AS credits_used
                FROM tasks
                WHERE user_id = :user_id
                  AND created_at > NOW() - MAKE_INTERVAL(days => :days)
                GROUP BY DATE(created_at), task_type
                ORDER BY date DESC, task_type
                LIMIT :limit OFFSET :offset
            """),
            {"user_id": user["id"], "days": days, "limit": page_size, "offset": offset},
        )
        rows = result.mappings().fetchall()

    return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/usage/summary")
async def get_usage_summary(user=Depends(get_current_user)):
    """用量汇总：总任务数、成功率、总消耗"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT
                    task_type,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'done') AS succeeded,
                    COALESCE(SUM(credits_charged), 0) AS total_credits
                FROM tasks
                WHERE user_id = :user_id
                GROUP BY task_type
            """),
            {"user_id": user["id"]},
        )
        rows = result.mappings().fetchall()

    return {"items": [dict(r) for r in rows], "total": len(rows)}


@router.get("/credits/history")
async def get_credits_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user),
):
    """积分流水明细"""
    offset = (page - 1) * page_size
    async with AsyncSessionLocal() as session:
        count_result = await session.execute(
            text("SELECT COUNT(*) FROM credit_transactions WHERE user_id = :uid"),
            {"uid": user["id"]},
        )
        total = count_result.scalar()

        result = await session.execute(
            text("""
                SELECT id, amount, tx_type, description, created_at
                FROM credit_transactions
                WHERE user_id = :uid
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"uid": user["id"], "limit": page_size, "offset": offset},
        )
        rows = result.mappings().fetchall()

    return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}

