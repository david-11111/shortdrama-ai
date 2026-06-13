import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings


settings = get_settings()

# Celery 线程池里每个任务调用 asyncio.run() 都会建新 loop；连接池里复用的
# asyncpg 连接绑死在旧 loop 上，会触发 "Event loop is closed" / "attached to a
# different loop"。worker 进程里禁掉连接复用，规避这个问题。
_is_worker = bool(os.environ.get("CELERY_WORKER"))
_is_testing = bool(os.environ.get("APP_TESTING"))

_engine_kwargs: dict = dict(
    echo=settings.app_debug,
    pool_pre_ping=True,
)
if _is_worker or _is_testing:
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_size"] = 20
    _engine_kwargs["max_overflow"] = 10

engine = create_async_engine(settings.database_url, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
