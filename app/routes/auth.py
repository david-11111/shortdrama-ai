"""
Auth routes: register/login/refresh/logout/current user.
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.middleware.auth import extract_bearer_token, get_current_user
from app.redis_client import redis_client
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserResponse
from app.security.token_blacklist import blacklist_token
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_expiry,
    get_token_jti,
    verify_password,
)
from app.services.users import create_user, get_user_by_email, get_user_by_id

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

MAX_FAILED_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 15 * 60
LOGIN_FAIL_KEY_PREFIX = "auth:login_fail:"


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _client_ip(request: Request) -> str:
    return (request.client.host if request.client else "") or ""


def _login_fail_key(email: str) -> str:
    return f"{LOGIN_FAIL_KEY_PREFIX}{email}"


def _is_password_strong(password: str) -> bool:
    # Length + uppercase + lowercase + number + symbol
    if len(password) < 10:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    if not re.search(r"[^A-Za-z0-9]", password):
        return False
    return True


async def _record_login_attempt(db: AsyncSession, email: str, ip: str, success: bool) -> None:
    await db.execute(
        text(
            """
            INSERT INTO login_attempts (email, ip, success)
            VALUES (:email, :ip, :success)
            """
        ),
        {"email": email, "ip": ip, "success": success},
    )
    await db.commit()


async def _failed_login_count_and_ttl(email: str) -> tuple[int, int]:
    key = _login_fail_key(email)
    count_raw = await redis_client.get(key)
    count = int(count_raw) if count_raw else 0
    ttl = await redis_client.ttl(key) if count > 0 else 0
    if ttl < 0:
        ttl = 0
    return count, ttl


async def _increase_failed_login(email: str) -> tuple[int, int]:
    key = _login_fail_key(email)
    count = int(await redis_client.incr(key))
    if count == 1:
        await redis_client.expire(key, LOGIN_LOCK_SECONDS)
    ttl = await redis_client.ttl(key)
    return count, max(ttl, 0)


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    email = _normalize_email(str(payload.email))

    if not _is_password_strong(payload.password):
        raise HTTPException(
            422,
            "Password too weak: require >=10 chars and include uppercase/lowercase/digit/symbol",
        )

    existing = await get_user_by_email(db, email)
    if existing:
        raise HTTPException(409, "Email already registered")

    user = await create_user(db, email, payload.password, payload.display_name)
    await db.commit()

    token_data = {"sub": str(user["id"]), "email": user["email"], "tier": user["tier"]}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_expire_minutes * 60,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    email = _normalize_email(str(payload.email))
    ip = _client_ip(request)

    failed_count, lock_ttl = await _failed_login_count_and_ttl(email)
    if failed_count >= MAX_FAILED_LOGIN_ATTEMPTS:
        raise HTTPException(429, f"Too many failed attempts. Try again in {lock_ttl} seconds")

    user = await get_user_by_email(db, email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        await _record_login_attempt(db, email, ip, False)
        failed_count, lock_ttl = await _increase_failed_login(email)
        if failed_count >= MAX_FAILED_LOGIN_ATTEMPTS:
            raise HTTPException(429, f"Too many failed attempts. Account locked for {lock_ttl} seconds")
        raise HTTPException(401, "Invalid email or password")

    if user["status"] != "active":
        await _record_login_attempt(db, email, ip, False)
        raise HTTPException(403, "Account is disabled")

    await _record_login_attempt(db, email, ip, True)
    await redis_client.delete(_login_fail_key(email))

    token_data = {"sub": str(user["id"]), "email": user["email"], "tier": user["tier"]}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        data = decode_token(payload.refresh_token)
    except Exception:
        raise HTTPException(401, "Invalid refresh token")

    if data.get("type") != "refresh":
        raise HTTPException(401, "Not a refresh token")

    user = await get_user_by_id(db, int(data["sub"]))
    if not user or user["status"] != "active":
        raise HTTPException(401, "User not found or disabled")

    token_data = {"sub": str(user["id"]), "email": user["email"], "tier": user["tier"]}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_expire_minutes * 60,
    )


@router.post("/logout")
async def logout(request: Request, current_user: dict = Depends(get_current_user)):
    token = extract_bearer_token(request)

    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    if payload.get("type") != "access":
        raise HTTPException(401, "Not an access token")

    token_jti = get_token_jti(token, payload)

    try:
        expires_at = get_token_expiry(payload)
        await blacklist_token(token_jti, int(current_user["id"]), expires_at)
    except Exception as exc:
        logger.error("Failed to blacklist token during logout: %s", exc)
        raise HTTPException(500, "Logout failed")

    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def me(current_user: dict = Depends(get_current_user)):
    return UserResponse(
        id=int(current_user["id"]),
        user_id=int(current_user["id"]),
        email=current_user["email"],
        display_name=current_user.get("display_name"),
        tier=current_user["tier"],
        tier_expires_at=(str(current_user.get("tier_expires_at")) if current_user.get("tier_expires_at") else None),
        status=current_user["status"],
        created_at=str(current_user["created_at"]),
    )
