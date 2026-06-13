"""
权限校验依赖。

使用方式:
    from app.middleware.permissions import require_tier

    @router.get("/pro-feature")
    async def pro_feature(user: dict = Depends(require_tier("pro"))):
        ...
"""
from fastapi import Depends, HTTPException

from app.middleware.auth import get_current_user

TIER_LEVELS = {"free": 0, "pro": 1, "enterprise": 2}


def require_tier(minimum_tier: str):
    """返回一个依赖，要求用户至少是指定等级"""
    min_level = TIER_LEVELS.get(minimum_tier, 0)

    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        user_level = TIER_LEVELS.get(current_user["tier"], 0)
        if user_level < min_level:
            raise HTTPException(403, f"This feature requires '{minimum_tier}' tier or above")
        return current_user

    return _check
