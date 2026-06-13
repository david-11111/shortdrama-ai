"""
Admin 鉴权中间件。
要求用户已登录且 is_admin = True。
"""
from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user


async def require_admin(
    request: Request,
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
    request.state.user = current_user
    return current_user
