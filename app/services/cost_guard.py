from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _today_bounds() -> tuple[datetime, datetime]:
    tz = ZoneInfo("Asia/Shanghai")
    today = datetime.now(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def get_cost_guard_status(db: AsyncSession, *, user_id: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    platform_limit = _decimal(settings.platform_daily_cost_limit_yuan)
    warn_ratio = _decimal(settings.platform_daily_cost_warn_ratio)
    start_at, end_at = _today_bounds()

    platform_row = (
        await db.execute(
            text(
                """
                SELECT
                    COALESCE((
                        SELECT SUM(CASE WHEN amount_yuan < 0 THEN -amount_yuan ELSE 0 END)
                        FROM volc_billing_rows
                        WHERE trade_time >= :start_at
                          AND trade_time < :end_at
                    ), 0) AS actual_yuan,
                    COALESCE((
                        SELECT SUM(estimated_cost_yuan)
                        FROM provider_usage_costs
                        WHERE created_at >= :start_at
                          AND created_at < :end_at
                    ), 0) AS estimated_yuan
                """
            ),
            {"start_at": start_at, "end_at": end_at},
        )
    ).mappings().first()

    actual_yuan = _decimal(platform_row["actual_yuan"])
    estimated_yuan = _decimal(platform_row["estimated_yuan"])
    observed_yuan = max(actual_yuan, estimated_yuan)
    platform_ratio = (observed_yuan / platform_limit) if platform_limit > 0 else Decimal("0")

    status: dict[str, Any] = {
        "platform": {
            "limit_yuan": str(platform_limit),
            "actual_yuan": str(actual_yuan),
            "estimated_yuan": str(estimated_yuan),
            "observed_yuan": str(observed_yuan),
            "usage_ratio": str(platform_ratio),
            "warning": platform_limit > 0 and platform_ratio >= warn_ratio,
            "blocked": platform_limit > 0 and observed_yuan >= platform_limit,
        },
        "user": None,
    }

    if user_id is not None:
        user_row = (
            await db.execute(
                text(
                    """
                    SELECT
                        COALESCE((
                            SELECT SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END)
                            FROM credit_transactions
                            WHERE user_id = :user_id
                              AND created_at >= :start_at
                              AND created_at < :end_at
                        ), 0) AS consumed,
                        usl.daily_credit_limit,
                        COALESCE(usl.is_unlimited, FALSE) AS is_unlimited,
                        usl.updated_at AS limit_updated_at
                    FROM users u
                    LEFT JOIN user_spend_limits usl ON usl.user_id = u.id
                    WHERE u.id = :user_id
                    """
                ),
                {"user_id": user_id, "start_at": start_at, "end_at": end_at},
            )
        ).mappings().first()
        default_limit = int(settings.user_daily_credit_limit)
        consumed = int((user_row or {}).get("consumed") or 0)
        is_unlimited = bool((user_row or {}).get("is_unlimited"))
        configured_limit = (user_row or {}).get("daily_credit_limit")
        effective_limit = None if is_unlimited else int(configured_limit or default_limit)
        remaining = None if effective_limit is None else max(effective_limit - consumed, 0)
        status["user"] = {
            "user_id": user_id,
            "daily_credit_limit": effective_limit,
            "configured_daily_credit_limit": configured_limit,
            "default_daily_credit_limit": default_limit,
            "is_unlimited": is_unlimited,
            "credits_consumed": consumed,
            "credits_remaining": remaining,
            "limit_updated_at": _isoformat((user_row or {}).get("limit_updated_at")),
            "blocked": effective_limit is not None and effective_limit > 0 and consumed >= effective_limit,
        }

    return status


async def assert_cost_guard(
    db: AsyncSession,
    *,
    user_id: int,
    credits_to_reserve: int = 0,
) -> None:
    status = await get_cost_guard_status(db, user_id=user_id)
    platform = status["platform"]
    if platform["blocked"]:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Platform daily cost limit reached",
                "cost_guard": status,
            },
        )

    user = status["user"] or {}
    if user.get("is_unlimited"):
        return

    user_limit = int(user.get("daily_credit_limit") or 0)
    consumed = int(user.get("credits_consumed") or 0)
    if user_limit > 0 and consumed + int(credits_to_reserve) > user_limit:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "User daily credit limit reached",
                "cost_guard": status,
                "credits_to_reserve": credits_to_reserve,
            },
        )
