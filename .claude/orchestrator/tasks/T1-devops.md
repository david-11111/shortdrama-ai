# T1 指令 — devops 终端

## 你的身份

你是 `devops` 终端。先读取 `.claude/team/devops.md` 了解你的权限边界。

## 任务目标

搭建 Phase 1 基础设施骨架：PostgreSQL + Redis + Celery 的运行环境和连接层。

## 分支

```bash
git checkout -b ops/phase1-infra
```

## 需要创建的文件

### 1. `requirements.txt`

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy[asyncio]==2.0.35
asyncpg==0.30.0
redis[hiredis]==5.2.0
celery[redis]==5.4.0
alembic==1.13.0
pydantic-settings==2.5.0
passlib[bcrypt]==1.7.4
python-jose[cryptography]==3.3.0
python-multipart==0.0.9
httpx==0.27.0
```

### 2. `.env.example`

```env
# PostgreSQL
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/saas_db

# Redis
REDIS_URL=redis://localhost:6379/0

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# JWT (Phase 2 用，先预留)
JWT_SECRET=change-me-in-production
JWT_EXPIRE_MINUTES=30

# 外部 API Keys (逗号分隔多个)
ARK_API_KEYS=key1,key2,key3

# 应用
APP_ENV=development
APP_DEBUG=true
APP_HOST=0.0.0.0
APP_PORT=8000
```

### 3. `app/config.py`

使用 Pydantic Settings，从环境变量读取所有配置：

```python
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/saas_db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # JWT
    jwt_secret: str = "change-me-in-production"
    jwt_expire_minutes: int = 30
    jwt_refresh_expire_days: int = 7

    # ARK API Keys (逗号分隔)
    ark_api_keys: str = ""

    # App
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    @property
    def ark_api_key_list(self) -> list[str]:
        return [k.strip() for k in self.ark_api_keys.split(",") if k.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### 4. `app/db.py`

SQLAlchemy async engine + session 工厂 + get_db 依赖注入：

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_debug,
    pool_size=20,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

### 5. `app/redis_client.py`

```python
import redis.asyncio as aioredis
from app.config import get_settings

settings = get_settings()

redis_pool = aioredis.ConnectionPool.from_url(
    settings.redis_url,
    max_connections=50,
    decode_responses=True,
)

redis_client = aioredis.Redis(connection_pool=redis_pool)

async def get_redis() -> aioredis.Redis:
    return redis_client
```

### 6. `docker-compose.yml`

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: saas_db
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  api:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - .:/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  worker-video:
    build:
      context: .
      dockerfile: Dockerfile
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: celery -A app.celery_app worker -Q video -c 4 --pool=threads -l info

  worker-image:
    build:
      context: .
      dockerfile: Dockerfile
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: celery -A app.celery_app worker -Q image -c 10 --pool=threads -l info

  worker-text:
    build:
      context: .
      dockerfile: Dockerfile
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: celery -A app.celery_app worker -Q text -c 20 --pool=threads -l info

volumes:
  pgdata:
  redisdata:
```

### 7. `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 8. `alembic.ini` + `alembic/` 目录

初始化 Alembic：
- `alembic.ini` — sqlalchemy.url 从环境变量读取
- `alembic/env.py` — 配置 async migration，import Base metadata
- `alembic/versions/001_initial_schema.py` — 建全部表

第一个迁移包含以下表（参考 `saas_architecture_plan.md` 第2章）：
- `users` — 用户表
- `api_keys` — 用户 API Key
- `credit_accounts` — 积分账户
- `credit_transactions` — 积分流水
- `credit_pricing` — 操作定价
- `tasks` — 任务表
- `dead_letter_tasks` — 死信任务
- `ark_api_keys` — 平台 Key 池
- `rate_limit_config` — 限流配置

所有字段严格按 `saas_architecture_plan.md` 第2章 SQL 定义。

## 验收标准

1. `docker-compose up postgres redis` 能正常启动
2. `alembic upgrade head` 能成功建表
3. `app/config.py`、`app/db.py`、`app/redis_client.py` 可被其他模块正常 import
4. `.env.example` 包含所有必要环境变量

## 完成后

告诉 orchestrator：T1 完成，列出创建的文件清单。
