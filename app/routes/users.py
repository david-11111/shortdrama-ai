"""
用户路由：API Key 管理。

端点:
  POST   /api/keys       → 创建 API Key
  GET    /api/keys       → 列出 API Key
  DELETE /api/keys/{id}  → 撤销 API Key
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.schemas.users import ApiKeyCreateRequest, ApiKeyResponse, ApiKeyListResponse
from app.security.hmac import generate_salt, compute_hmac_hash

router = APIRouter(prefix="/keys", tags=["api-keys"])


def _generate_api_key() -> tuple[str, str, str, str]:
    """生成 API Key，返回 (key_id, raw_key, key_hash, salt)"""
    key_id = secrets.token_hex(16)
    raw_key = f"sk_live_{secrets.token_urlsafe(32)}"
    salt = generate_salt()
    key_hash = compute_hmac_hash(raw_key, salt)
    return key_id, raw_key, key_hash, salt


@router.post("", response_model=ApiKeyResponse, status_code=201)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    key_id, raw_key, key_hash, salt = _generate_api_key()

    async with db.begin():
        await db.execute(
            text("""
                INSERT INTO api_keys (key_id, key_hash, hmac_salt, user_id, name)
                VALUES (:key_id, :key_hash, :hmac_salt, :user_id, :name)
            """),
            {"key_id": key_id, "key_hash": key_hash, "hmac_salt": salt,
             "user_id": current_user["id"], "name": payload.name}
        )

    return ApiKeyResponse(key_id=key_id, name=payload.name, created_at="just now", api_key=raw_key)


@router.get("", response_model=ApiKeyListResponse)
async def list_api_keys(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("""
            SELECT key_id, name, created_at
            FROM api_keys
            WHERE user_id = :user_id AND revoked = FALSE
            ORDER BY created_at DESC
        """),
        {"user_id": current_user["id"]}
    )
    rows = result.mappings().fetchall()
    keys = [ApiKeyResponse(key_id=r["key_id"], name=r["name"], created_at=str(r["created_at"])) for r in rows]
    return ApiKeyListResponse(keys=keys)


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    async with db.begin():
        result = await db.execute(
            text("UPDATE api_keys SET revoked = TRUE WHERE key_id = :key_id AND user_id = :user_id"),
            {"key_id": key_id, "user_id": current_user["id"]}
        )
        if result.rowcount == 0:
            raise HTTPException(404, "API Key not found")

    return {"message": "API Key revoked"}
