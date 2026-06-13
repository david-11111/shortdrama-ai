"""
用户服务 — 注册、查询、更新。

操作 users 表和 credit_accounts 表。
注册时自动创建积分账户并赠送初始积分。
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import hash_password

INITIAL_CREDITS = 50  # 注册赠送积分


async def create_user(session: AsyncSession, email: str, password: str, display_name: str | None = None) -> dict:
    """
    创建用户 + 积分账户。
    返回 {"id": int, "user_id": uuid_str, "email": str, "tier": str}
    """
    password_hash = hash_password(password)

    result = await session.execute(
        text("""
            INSERT INTO users (email, password_hash, display_name)
            VALUES (:email, :password_hash, :display_name)
            RETURNING id, user_id, email, tier, status, created_at
        """),
        {"email": email, "password_hash": password_hash, "display_name": display_name}
    )
    user = result.mappings().fetchone()

    # 创建积分账户并赠送初始积分
    await session.execute(
        text("""
            INSERT INTO credit_accounts (user_id, balance, lifetime_earned)
            VALUES (:user_id, :balance, :earned)
        """),
        {"user_id": user["id"], "balance": INITIAL_CREDITS, "earned": INITIAL_CREDITS}
    )

    # 写积分流水
    await session.execute(
        text("""
            INSERT INTO credit_transactions (user_id, amount, balance_after, tx_type, description)
            VALUES (:user_id, :amount, :balance, 'bonus', 'Registration bonus')
        """),
        {"user_id": user["id"], "amount": INITIAL_CREDITS, "balance": INITIAL_CREDITS}
    )

    return dict(user)


async def get_user_by_email(session: AsyncSession, email: str) -> dict | None:
    result = await session.execute(
        text(
            """
            SELECT id, user_id, email, password_hash, display_name,
                   CASE
                       WHEN tier != 'free' AND tier_expires_at IS NOT NULL AND tier_expires_at < NOW() THEN 'free'
                       ELSE tier
                   END AS tier,
                   tier_expires_at, status, created_at
            FROM users
            WHERE email = :email
            """
        ),
        {"email": email}
    )
    row = result.mappings().fetchone()
    return dict(row) if row else None


async def get_user_by_id(session: AsyncSession, user_id: int) -> dict | None:
    result = await session.execute(
        text(
            """
            SELECT id, user_id, email, display_name,
                   CASE
                       WHEN tier != 'free' AND tier_expires_at IS NOT NULL AND tier_expires_at < NOW() THEN 'free'
                       ELSE tier
                   END AS tier,
                   tier_expires_at, status, created_at
            FROM users
            WHERE id = :id
            """
        ),
        {"id": user_id}
    )
    row = result.mappings().fetchone()
    return dict(row) if row else None


async def get_user_by_api_key_hash(session: AsyncSession, key_hash: str) -> dict | None:
    """通过 API Key hash 查找用户"""
    result = await session.execute(
        text("""
            SELECT u.id, u.user_id, u.email, u.display_name,
                   CASE
                       WHEN u.tier != 'free' AND u.tier_expires_at IS NOT NULL AND u.tier_expires_at < NOW() THEN 'free'
                       ELSE u.tier
                   END AS tier,
                   u.status, u.created_at, u.tier_expires_at
            FROM users u
            JOIN api_keys ak ON ak.user_id = u.id
            WHERE ak.key_hash = :key_hash AND ak.revoked = FALSE
              AND (ak.expires_at IS NULL OR ak.expires_at > NOW())
        """),
        {"key_hash": key_hash}
    )
    row = result.mappings().fetchone()
    return dict(row) if row else None
