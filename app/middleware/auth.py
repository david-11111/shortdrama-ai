"""
Authentication dependency helpers.
Supports:
1) Bearer JWT access token
2) Bearer API Key (sk_live_...)
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.security.hmac import verify_api_key, compute_legacy_hash
from app.security.token_blacklist import is_token_blacklisted
from app.services.auth import decode_token, get_token_jti
from app.services.users import get_user_by_id


def extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    return auth_header[7:]


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    token = extract_bearer_token(request)

    # API Key mode
    if token.startswith("sk_live_"):
        legacy_hash = compute_legacy_hash(token)
        result = await db.execute(
            text("""
                SELECT u.id, u.user_id, u.email, u.display_name,
                       CASE
                           WHEN u.tier != 'free' AND u.tier_expires_at IS NOT NULL AND u.tier_expires_at < NOW() THEN 'free'
                           ELSE u.tier
                       END AS tier,
                       u.status, u.created_at,
                       u.tier_expires_at,
                       ak.key_hash, ak.hmac_salt
                FROM users u
                JOIN api_keys ak ON ak.user_id = u.id
                WHERE ak.revoked = FALSE
                  AND (ak.expires_at IS NULL OR ak.expires_at > NOW())
                  AND (ak.key_hash = :legacy_hash OR ak.hmac_salt IS NOT NULL)
            """),
            {"legacy_hash": legacy_hash},
        )
        rows = result.mappings().fetchall()

        user = None
        for row in rows:
            if verify_api_key(token, row["key_hash"], row["hmac_salt"]):
                user = dict(row)
                break

        if not user:
            raise HTTPException(401, "Invalid API Key")
        if user["status"] != "active":
            raise HTTPException(403, "Account is disabled")
        return user

    # JWT mode
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    if payload.get("type") != "access":
        raise HTTPException(401, "Not an access token")

    token_jti = get_token_jti(token, payload)
    if await is_token_blacklisted(token_jti):
        raise HTTPException(401, "Token has been revoked")

    user = await get_user_by_id(db, int(payload["sub"]))
    if not user:
        raise HTTPException(401, "User not found")
    if user["status"] != "active":
        raise HTTPException(403, "Account is disabled")

    return user
