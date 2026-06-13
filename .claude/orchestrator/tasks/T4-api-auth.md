# T4 指令 — api-auth 终端

## 你的身份

你是 `api-auth` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

先读取 `D:/20240313整理文件/Desktop/saas/.claude/team/api-auth.md` 了解你的权限边界。

## 前置条件

Phase 1 已完成，以下文件已就绪：
- `app/config.py` — 含 `jwt_secret`、`jwt_expire_minutes`、`jwt_refresh_expire_days`
- `app/db.py` — `AsyncSessionLocal`、`get_db`、`Base`
- `app/redis_client.py` — `redis_client`（async Redis）
- `alembic/versions/001_initial_schema.py` — 已有 `users` 表和 `api_keys` 表

## 任务目标

实现完整的用户认证系统：注册、登录、Token 刷新、用户信息查询、API Key 管理、鉴权中间件。

## 分支

```bash
git checkout -b auth/phase2-user-system
```

## 需要创建的文件

### 1. `app/services/auth.py`

认证核心服务：

```python
"""
认证服务 — 密码哈希、JWT 生成与验证。

依赖:
- passlib[bcrypt] 做密码哈希
- python-jose[cryptography] 做 JWT
- app/config.py 读取 jwt_secret、过期时间
- app/redis_client.py 做 Token 黑名单
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- 密码 ---

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

# --- JWT ---

def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")

def create_refresh_token(data: dict[str, Any]) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")

def decode_token(token: str) -> dict[str, Any]:
    """解码 JWT，失败抛 JWTError"""
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
```

### 2. `app/services/users.py`

用户 CRUD 服务：

```python
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
        text("SELECT id, user_id, email, password_hash, display_name, tier, status, created_at FROM users WHERE email = :email"),
        {"email": email}
    )
    row = result.mappings().fetchone()
    return dict(row) if row else None

async def get_user_by_id(session: AsyncSession, user_id: int) -> dict | None:
    result = await session.execute(
        text("SELECT id, user_id, email, display_name, tier, status, created_at FROM users WHERE id = :id"),
        {"id": user_id}
    )
    row = result.mappings().fetchone()
    return dict(row) if row else None

async def get_user_by_api_key_hash(session: AsyncSession, key_hash: str) -> dict | None:
    """通过 API Key hash 查找用户"""
    result = await session.execute(
        text("""
            SELECT u.id, u.user_id, u.email, u.display_name, u.tier, u.status, u.created_at
            FROM users u
            JOIN api_keys ak ON ak.user_id = u.id
            WHERE ak.key_hash = :key_hash AND ak.revoked = FALSE
              AND (ak.expires_at IS NULL OR ak.expires_at > NOW())
        """),
        {"key_hash": key_hash}
    )
    row = result.mappings().fetchone()
    return dict(row) if row else None
```

### 3. `app/schemas/auth.py`

```python
from pydantic import BaseModel, EmailStr, Field

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒

class RefreshRequest(BaseModel):
    refresh_token: str

class UserResponse(BaseModel):
    id: int
    user_id: str
    email: str
    display_name: str | None
    tier: str
    status: str
    created_at: str
```

### 4. `app/schemas/users.py`

```python
from pydantic import BaseModel

class UserProfileResponse(BaseModel):
    id: int
    user_id: str
    email: str
    display_name: str | None
    tier: str
    credits_balance: int

class ApiKeyCreateRequest(BaseModel):
    name: str = "default"

class ApiKeyResponse(BaseModel):
    key_id: str
    name: str
    created_at: str
    # 完整 key 只在创建时返回一次
    api_key: str | None = None

class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyResponse]
```

### 5. `app/routes/auth.py`

```python
"""
认证路由：注册、登录、刷新 Token、获取当前用户信息。

端点:
  POST /api/auth/register  → 注册
  POST /api/auth/login     → 登录
  POST /api/auth/refresh   → 刷新 Token
  GET  /api/auth/me        → 当前用户信息
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, RefreshRequest, UserResponse
from app.services.auth import verify_password, create_access_token, create_refresh_token, decode_token
from app.services.users import create_user, get_user_by_email, get_user_by_id
from app.middleware.auth import get_current_user
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # 检查邮箱是否已注册
    existing = await get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(409, "Email already registered")

    async with db.begin():
        user = await create_user(db, payload.email, payload.password, payload.display_name)

    token_data = {"sub": str(user["id"]), "email": user["email"], "tier": user["tier"]}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_expire_minutes * 60,
    )

@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await get_user_by_email(db, payload.email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    if user["status"] != "active":
        raise HTTPException(403, "Account is disabled")

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

@router.get("/me", response_model=UserResponse)
async def me(current_user: dict = Depends(get_current_user)):
    return UserResponse(
        id=current_user["id"],
        user_id=str(current_user["user_id"]),
        email=current_user["email"],
        display_name=current_user.get("display_name"),
        tier=current_user["tier"],
        status=current_user["status"],
        created_at=str(current_user["created_at"]),
    )
```

### 6. `app/routes/users.py`

```python
"""
用户路由：API Key 管理。

端点:
  POST   /api/keys       → 创建 API Key
  GET    /api/keys       → 列出 API Key
  DELETE /api/keys/{id}  → 撤销 API Key
"""
import secrets
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.schemas.users import ApiKeyCreateRequest, ApiKeyResponse, ApiKeyListResponse

router = APIRouter(prefix="/keys", tags=["api-keys"])

def _generate_api_key() -> tuple[str, str, str]:
    """生成 API Key，返回 (key_id, raw_key, key_hash)"""
    key_id = secrets.token_hex(16)  # 32 chars
    raw_key = f"sk_live_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return key_id, raw_key, key_hash

@router.post("", response_model=ApiKeyResponse, status_code=201)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    key_id, raw_key, key_hash = _generate_api_key()

    async with db.begin():
        await db.execute(
            text("""
                INSERT INTO api_keys (key_id, key_hash, user_id, name)
                VALUES (:key_id, :key_hash, :user_id, :name)
            """),
            {"key_id": key_id, "key_hash": key_hash, "user_id": current_user["id"], "name": payload.name}
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
```

### 7. `app/middleware/auth.py`

鉴权中间件 — 支持 JWT 和 API Key 两种方式：

```python
"""
鉴权依赖注入。

使用方式:
    from app.middleware.auth import get_current_user

    @router.get("/protected")
    async def protected(user: dict = Depends(get_current_user)):
        ...

支持两种认证方式:
1. Bearer Token (JWT): Authorization: Bearer <jwt_token>
2. API Key: Authorization: Bearer sk_live_xxxxx
"""
import hashlib

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.auth import decode_token
from app.services.users import get_user_by_id, get_user_by_api_key_hash


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """
    从 Authorization header 提取用户信息。
    支持 JWT access_token 和 API Key (sk_live_xxx)。
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")

    token = auth_header[7:]  # 去掉 "Bearer "

    # API Key 方式
    if token.startswith("sk_live_"):
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        user = await get_user_by_api_key_hash(db, key_hash)
        if not user:
            raise HTTPException(401, "Invalid API Key")
        if user["status"] != "active":
            raise HTTPException(403, "Account is disabled")
        return user

    # JWT 方式
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    if payload.get("type") != "access":
        raise HTTPException(401, "Not an access token")

    user = await get_user_by_id(db, int(payload["sub"]))
    if not user:
        raise HTTPException(401, "User not found")
    if user["status"] != "active":
        raise HTTPException(403, "Account is disabled")

    return user
```

### 8. `app/middleware/permissions.py`

权限校验（基于 tier）：

```python
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
```

### 9. 注册路由到 `app/routes/__init__.py`

修改现有的 `app/routes/__init__.py`，加入 auth 和 users 路由：

```python
from fastapi import APIRouter
from app.routes.tasks import router as tasks_router
from app.routes.auth import router as auth_router
from app.routes.users import router as users_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(tasks_router)
```

## 验收标准

1. `POST /api/auth/register` — 注册成功返回 JWT + 自动创建积分账户（50积分）
2. `POST /api/auth/login` — 登录成功返回 access_token + refresh_token
3. `POST /api/auth/refresh` — 用 refresh_token 换新 token 对
4. `GET /api/auth/me` — 带 Bearer Token 返回用户信息
5. `POST /api/keys` — 创建 API Key，返回完整 key（仅一次）
6. `GET /api/keys` — 列出用户的 API Key（不含完整 key）
7. `DELETE /api/keys/{key_id}` — 撤销 API Key
8. `get_current_user` 依赖同时支持 JWT 和 API Key 认证
9. 密码使用 bcrypt 哈希，不存明文
10. Token 过期时间从 config 读取

## 完成后

告诉 orchestrator：T4 完成，列出创建/修改的文件清单。
