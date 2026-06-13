"""
pytest 全局 fixtures。

环境要求（集成/e2e 测试）:
  - TEST_DATABASE_URL: postgresql+asyncpg://...
  - TEST_REDIS_URL: redis://...
  - 或使用 docker-compose -f docker-compose.test.yml up -d 启动依赖

单元测试无需任何外部依赖。
"""
import asyncio
import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# ─── 测试数据库 URL ──────────────────────────────────────────────────────────────

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/saas_test",
)
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("APP_TESTING", "1")
_DB_AVAILABLE: bool | None = None


def _test_database_available() -> bool:
    global _DB_AVAILABLE
    if _DB_AVAILABLE is not None:
        return _DB_AVAILABLE

    async def check() -> bool:
        engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            await engine.dispose()

    try:
        _DB_AVAILABLE = asyncio.run(check())
    except Exception:
        _DB_AVAILABLE = False
    return _DB_AVAILABLE


def pytest_collection_modifyitems(config, items):
    db_required = pytest.mark.skip(reason="TEST_DATABASE_URL is not available")
    db_items = []
    for item in items:
        item_path = str(item.path).replace("\\", "/")
        if (
            "integration" in item.keywords
            or "e2e" in item.keywords
            or "/tests/integration/" in item_path
            or "/tests/e2e/" in item_path
        ):
            db_items.append(item)
    if db_items and not _test_database_available():
        for item in db_items:
            item.add_marker(db_required)


# ─── 测试数据库引擎 ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    if not _test_database_available():
        pytest.skip("TEST_DATABASE_URL is not available")
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def test_session_factory(test_engine):
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(test_session_factory) -> AsyncGenerator[AsyncSession, None]:
    """每个测试独立事务，测试结束后回滚。"""
    async with test_session_factory() as session:
        await session.begin()
        yield session
        await session.rollback()


# ─── FastAPI 测试客户端 ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def isolate_app_redis_connections():
    await _close_app_redis_connections()
    yield
    await _close_app_redis_connections()


async def _close_app_redis_connections() -> None:
    try:
        from app import redis_client as app_redis

        try:
            await app_redis.redis_client.aclose(close_connection_pool=False)
        except AttributeError:
            await app_redis.redis_client.close(close_connection_pool=False)
        try:
            await app_redis.redis_pool.disconnect(inuse_connections=True)
        except TypeError:
            await app_redis.redis_pool.disconnect()
    except Exception:
        return


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    注入测试 DB session 的 ASGI 客户端。
    覆盖 get_db 依赖，使路由使用同一个事务 session（可回滚）。
    """
    import app.main as main_module
    from app.db import get_db

    async def override_get_db():
        yield db_session

    main_module.app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=main_module.app),
        base_url="http://test",
    ) as ac:
        yield ac

    main_module.app.dependency_overrides.clear()


# ─── 测试用户 fixtures ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_user_free(db_session: AsyncSession) -> dict:
    return await _create_test_user(db_session, "free")


@pytest_asyncio.fixture
async def test_user_pro(db_session: AsyncSession) -> dict:
    return await _create_test_user(db_session, "pro")


@pytest_asyncio.fixture
async def test_user_enterprise(db_session: AsyncSession) -> dict:
    return await _create_test_user(db_session, "enterprise")


async def _create_test_user(session: AsyncSession, tier: str) -> dict:
    import uuid
    from app.services.auth import hash_password, create_access_token

    username = f"qa_test_{tier}_{uuid.uuid4().hex[:6]}"
    email = f"{username}@qa.test"
    password_hash = hash_password("TestPass123!")

    result = await session.execute(
        text("""
            INSERT INTO users (email, password_hash, display_name, tier, status)
            VALUES (:email, :password_hash, :username, :tier, 'active')
            RETURNING id
        """),
        {"username": username, "email": email, "password_hash": password_hash, "tier": tier},
    )
    user_id = result.scalar()

    # 创建积分账户（初始 1000 积分）
    await session.execute(
        text("""
            INSERT INTO credit_accounts (user_id, balance)
            VALUES (:user_id, 1000)
        """),
        {"user_id": user_id},
    )

    token = create_access_token({"sub": str(user_id)})
    return {
        "id": user_id,
        "username": username,
        "email": email,
        "tier": tier,
        "token": token,
        "auth_header": f"Bearer {token}",
    }


# ─── 限流配置 fixture ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def rate_limit_config(db_session: AsyncSession):
    """插入三档 tier 的限流配置。"""
    configs = [
        # (tier, resource, window_seconds, max_count)
        ("free", "video_gen", 3600, 5),
        ("free", "image_gen", 3600, 20),
        ("free", "concurrent_tasks", 0, 2),
        ("pro", "video_gen", 3600, 30),
        ("pro", "image_gen", 3600, 100),
        ("pro", "concurrent_tasks", 0, 10),
        ("enterprise", "video_gen", 3600, 200),
        ("enterprise", "image_gen", 3600, 500),
        ("enterprise", "concurrent_tasks", 0, 50),
    ]
    for tier, resource, window, max_count in configs:
        await db_session.execute(
            text("""
                INSERT INTO rate_limit_config (tier, resource, window_seconds, max_count)
                VALUES (:tier, :resource, :window_seconds, :max_count)
                ON CONFLICT (tier, resource) DO UPDATE
                SET window_seconds = EXCLUDED.window_seconds,
                    max_count = EXCLUDED.max_count
            """),
            {"tier": tier, "resource": resource, "window_seconds": window, "max_count": max_count},
        )
