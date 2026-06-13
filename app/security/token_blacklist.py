"""
JWT Token 黑名单 — Redis 缓存 + PostgreSQL 持久化。

Redis key: token_blacklist:{jti}  TTL = token 剩余有效期
DB 表: token_blacklist（持久化，用于 Redis 重启后恢复）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.redis_client import redis_client

logger = logging.getLogger(__name__)

_REDIS_PREFIX = "token_blacklist:"


async def blacklist_token(jti: str, user_id: int, expires_at: datetime) -> None:
    """将 Token 加入黑名单（Redis + DB）"""
    now = datetime.now(timezone.utc)
    ttl_seconds = max(int((expires_at - now).total_seconds()), 1)

    # Redis 缓存（快速检查）
    await redis_client.setex(f"{_REDIS_PREFIX}{jti}", ttl_seconds, "1")

    # DB 持久化
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("""
                    INSERT INTO token_blacklist (jti, user_id, expires_at)
                    VALUES (:jti, :user_id, :expires_at)
                    ON CONFLICT (jti) DO NOTHING
                """),
                {"jti": jti, "user_id": user_id, "expires_at": expires_at},
            )


async def is_token_blacklisted(jti: str) -> bool:
    """检查 Token 是否在黑名单中（优先 Redis，降级到 DB）"""
    try:
        result = await redis_client.get(f"{_REDIS_PREFIX}{jti}")
        if result is not None:
            return True
    except aioredis.RedisError as exc:
        logger.warning("Redis blacklist check failed, falling back to DB: %s", exc)

    # Redis 不可用时降级到 DB
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT 1 FROM token_blacklist
                WHERE jti = :jti AND expires_at > NOW()
            """),
            {"jti": jti},
        )
        return result.scalar() is not None


async def cleanup_expired_blacklist() -> int:
    """清理过期黑名单记录（供定时任务调用）"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                text("DELETE FROM token_blacklist WHERE expires_at <= NOW()")
            )
            return result.rowcount
