from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.services.cost_guard import get_cost_guard_status

router = APIRouter(prefix="/credits", tags=["credits"])


class SpendLimitUpdate(BaseModel):
    is_unlimited: bool = False
    daily_credit_limit: int | None = Field(default=None, ge=1, le=1_000_000)


@router.get("")
async def get_credits(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
    offset = (page - 1) * page_size
    result = await db.execute(
        text(
            """
            SELECT amount, balance_after, tx_type, reference_id, description, created_at
            FROM credit_transactions
            WHERE user_id = :uid
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"uid": current_user["id"], "limit": page_size, "offset": offset},
    )
    rows = result.mappings().fetchall()
    return {"transactions": [dict(r) for r in rows], "page": page, "page_size": page_size}


@router.get("/pricing")
async def get_pricing(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT operation, credits_cost, tier_overrides FROM credit_pricing WHERE active = TRUE")
    )
    rows = result.mappings().fetchall()
    return {"pricing": [dict(r) for r in rows]}


@router.get("/spend-limit")
async def get_spend_limit(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    status = await get_cost_guard_status(db, user_id=current_user["id"])
    return status["user"]


@router.put("/spend-limit")
async def update_spend_limit(
    payload: SpendLimitUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    limit = None if payload.is_unlimited else payload.daily_credit_limit
    if not payload.is_unlimited and limit is None:
        current_status = await get_cost_guard_status(db, user_id=current_user["id"])
        limit = int(current_status["user"]["default_daily_credit_limit"])

    await db.execute(
        text(
            """
            INSERT INTO user_spend_limits (user_id, daily_credit_limit, is_unlimited, updated_at)
            VALUES (:user_id, :daily_credit_limit, :is_unlimited, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET daily_credit_limit = EXCLUDED.daily_credit_limit,
                is_unlimited = EXCLUDED.is_unlimited,
                updated_at = NOW()
            """
        ),
        {
            "user_id": current_user["id"],
            "daily_credit_limit": limit,
            "is_unlimited": payload.is_unlimited,
        },
    )
    await db.commit()

    status = await get_cost_guard_status(db, user_id=current_user["id"])
    return status["user"]
