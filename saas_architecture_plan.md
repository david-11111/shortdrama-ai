# SaaS 平台化工程方案

## Context

当前系统是单用户 AI 视频生成工具，需要升级为支持 20-1000+ 并发用户的 SaaS 平台。核心问题：单 API key 串行调用无法支撑多用户并发，缺少用户系统、任务队列、计费体系。参考架构：Claude API 的 queue → scheduler → worker pool → streaming response 模式。

---

## 1. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                         EDGE LAYER                               │
│  Nginx / 云 LB  →  Rate Limiter (Redis 滑动窗口)                │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                    API SERVERS (N 副本, 无状态)                   │
│  FastAPI + Uvicorn                                               │
│  ┌────────┐ ┌──────────┐ ┌────────────┐ ┌───────────┐          │
│  │Auth MW │ │Credits MW│ │Rate Limit  │ │WebSocket  │          │
│  └────────┘ └──────────┘ └────────────┘ └───────────┘          │
└────────┬────────────┬────────────┬──────────────┬───────────────┘
         │            │            │              │
┌────────▼───┐  ┌─────▼─────┐  ┌──▼───┐  ┌──────▼──────┐
│ PostgreSQL │  │   Redis    │  │Redis │  │   Redis     │
│ (主数据库) │  │ (任务队列  │  │(缓存 │  │  (pub/sub   │
│            │  │  + Celery) │  │+ 限流)│  │   WebSocket)│
└────────────┘  └─────┬──────┘  └──────┘  └─────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────┐
│                      WORKER POOL                                  │
│  Celery workers (按队列自动扩缩)                                  │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                 │
│  │ video_gen  │  │ image_gen  │  │  llm_text  │                 │
│  │ 并发=2/key │  │ 并发=5/key │  │ 并发=10/key│                 │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘                 │
│        └────────────────┼───────────────┘                        │
│                   ┌─────▼─────┐                                  │
│                   │ Key Pool  │ (多key轮询 + 负载感知)            │
│                   └───────────┘                                  │
└─────────────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────┐
│                   EXTERNAL APIs                                   │
│  Seedance (视频)  │  Seedream (图片)  │  Doubao (文本)           │
└─────────────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────┐
│                     STORAGE                                       │
│  Volcengine TOS (对象存储, 按用户前缀隔离)                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 数据库设计 (PostgreSQL)

### 2.1 用户与认证

```sql
CREATE TABLE users (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name  VARCHAR(100),
    tier          VARCHAR(20) NOT NULL DEFAULT 'free',
    status        VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE api_keys (
    id          BIGSERIAL PRIMARY KEY,
    key_id      VARCHAR(32) NOT NULL UNIQUE,
    key_hash    VARCHAR(255) NOT NULL,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        VARCHAR(100),
    scopes      JSONB NOT NULL DEFAULT '["all"]',
    last_used_at TIMESTAMPTZ,
    expires_at  TIMESTAMPTZ,
    revoked     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 2.2 积分与计费

```sql
CREATE TABLE credit_accounts (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL UNIQUE REFERENCES users(id),
    balance         INTEGER NOT NULL DEFAULT 0,
    lifetime_earned INTEGER NOT NULL DEFAULT 0,
    lifetime_spent  INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE credit_transactions (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id),
    amount        INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    tx_type       VARCHAR(30) NOT NULL,
    reference_id  VARCHAR(64),
    description   VARCHAR(255),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE credit_pricing (
    id           BIGSERIAL PRIMARY KEY,
    operation    VARCHAR(50) NOT NULL UNIQUE,
    credits_cost INTEGER NOT NULL,
    tier_overrides JSONB DEFAULT '{}',
    active       BOOLEAN NOT NULL DEFAULT TRUE
);

-- 定价种子数据
INSERT INTO credit_pricing (operation, credits_cost) VALUES
    ('video_gen_5s', 10),
    ('video_gen_8s', 15),
    ('video_gen_10s', 20),
    ('image_gen', 2),
    ('llm_refine', 1),
    ('llm_director_chat', 1),
    ('pipeline_analysis', 5);
```

### 2.3 任务队列 (替代内存 job_registry)

```sql
CREATE TABLE tasks (
    id              BIGSERIAL PRIMARY KEY,
    task_id         UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    project_id      VARCHAR(32),
    task_type       VARCHAR(50) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    priority        SMALLINT NOT NULL DEFAULT 5,
    payload         JSONB NOT NULL DEFAULT '{}',
    result          JSONB,
    error_message   TEXT,
    error_code      VARCHAR(50),
    retry_count     SMALLINT NOT NULL DEFAULT 0,
    max_retries     SMALLINT NOT NULL DEFAULT 3,
    celery_task_id  VARCHAR(64),
    progress        SMALLINT NOT NULL DEFAULT 0,
    stage_text      VARCHAR(200),
    credits_reserved INTEGER NOT NULL DEFAULT 0,
    credits_charged  INTEGER NOT NULL DEFAULT 0,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tasks_user_status ON tasks(user_id, status);
CREATE INDEX idx_tasks_status_priority ON tasks(status, priority, created_at);

CREATE TABLE dead_letter_tasks (
    id               BIGSERIAL PRIMARY KEY,
    original_task_id UUID NOT NULL,
    user_id          BIGINT NOT NULL,
    task_type        VARCHAR(50) NOT NULL,
    payload          JSONB NOT NULL,
    error_history    JSONB NOT NULL DEFAULT '[]',
    dead_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved         BOOLEAN NOT NULL DEFAULT FALSE
);
```

### 2.4 API Key 池 (平台持有的外部服务 key)

```sql
CREATE TABLE ark_api_keys (
    id                BIGSERIAL PRIMARY KEY,
    key_name          VARCHAR(50) NOT NULL UNIQUE,
    encrypted_key     TEXT NOT NULL,
    provider          VARCHAR(30) NOT NULL DEFAULT 'ark',
    services          JSONB NOT NULL DEFAULT '["seedance","seedream","doubao"]',
    concurrency_limit INTEGER NOT NULL DEFAULT 2,
    current_load      INTEGER NOT NULL DEFAULT 0,
    rpm_limit         INTEGER NOT NULL DEFAULT 60,
    status            VARCHAR(20) NOT NULL DEFAULT 'active',
    cooldown_until    TIMESTAMPTZ,
    last_used_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 2.5 限流配置

```sql
CREATE TABLE rate_limit_config (
    id             BIGSERIAL PRIMARY KEY,
    tier           VARCHAR(20) NOT NULL,
    resource       VARCHAR(50) NOT NULL,
    window_seconds INTEGER NOT NULL,
    max_count      INTEGER NOT NULL,
    UNIQUE(tier, resource)
);

INSERT INTO rate_limit_config (tier, resource, window_seconds, max_count) VALUES
    ('free', 'concurrent_tasks', 1, 2),
    ('free', 'video_gen', 3600, 5),
    ('free', 'image_gen', 3600, 20),
    ('pro', 'concurrent_tasks', 1, 10),
    ('pro', 'video_gen', 3600, 50),
    ('pro', 'image_gen', 3600, 200),
    ('enterprise', 'concurrent_tasks', 1, 50),
    ('enterprise', 'video_gen', 3600, 200),
    ('enterprise', 'image_gen', 3600, 1000);
```

---

## 3. 任务生命周期

```
用户请求
    │
    ▼
[鉴权] ──失败──▶ 401 Unauthorized
    │ 通过
    ▼
[积分检查] ──不足──▶ 402 Insufficient Credits
    │ 足够
    ▼
[限流检查] ──超限──▶ 429 Too Many Requests (返回 retry-after)
    │ 通过
    ▼
[预扣积分] ──▶ credit_transactions 写入
    │
    ▼
[创建任务] ──▶ tasks 表 (status=pending)
    │
    ▼
[入队 Celery] ──▶ Redis 队列 (按 priority 路由)
    │               video_gen → queue:video
    │               image_gen → queue:image
    │               llm_text  → queue:text
    ▼
[返回 202] ──▶ {task_id, status: "queued", estimated_wait}
    │
    ▼ (异步)
[Worker 取任务] ──▶ status=running, 获取 API key
    │
    ├── 成功 ──▶ status=done, 扣实际积分, 退还多余预扣
    │            发布 Redis pub/sub → WebSocket 推送给用户
    │
    ├── 可重试错误(超时/429/500) ──▶ retry_count++, 指数退避重入队
    │   退避: 30s → 120s → 300s
    │
    ├── Policy Violation ──▶ 自动 sanitize prompt 重试一次
    │   仍失败 → status=failed, 退还积分
    │
    └── 超过最大重试 ──▶ 移入 dead_letter_tasks
                         status=dead_letter, 退还积分, 通知管理员
```

---

## 4. Worker 池与 Key 轮询

### 4.1 Key Pool Manager

文件: `app/services/key_pool.py`

```python
class KeyPool:
    """
    管理平台持有的多把 ARK API key。
    
    Redis 原子计数器跟踪每把 key 的并发负载:
      ark_key:{name}:load     → 当前并发数 (INCR/DECR)
      ark_key:{name}:cooldown → 冷却到期时间 (TTL key)
      ark_key:{name}:rpm      → 本分钟请求数 (INCR + EXPIRE 60s)
    """
    
    def acquire(self, service: str) -> tuple[str, str]:
        """获取负载最低的可用 key。无可用 key 时抛 BackpressureError。"""
        
    def release(self, key_name: str):
        """请求完成后释放 (DECR load)。"""
        
    def report_error(self, key_name: str, error_type: str):
        """429→冷却60s, 500→冷却30s, 连续3次→冷却300s"""
```

### 4.2 并发控制

| 服务 | 单 key 并发上限 | 5把 key 总并发 | 10把 key 总并发 |
|------|----------------|---------------|----------------|
| Seedance (视频) | 2 | 10 | 20 |
| Seedream (图片) | 5 | 25 | 50 |
| Doubao (文本) | 10 | 50 | 100 |

### 4.3 Celery Worker 配置

```bash
# 视频队列: 并发=key数×2
celery -A app.celery_app worker -Q video -c 4 --pool=threads

# 图片队列: 并发=key数×5
celery -A app.celery_app worker -Q image -c 10 --pool=threads

# 文本队列: 并发=key数×10
celery -A app.celery_app worker -Q text -c 20 --pool=threads
```

### 4.4 Celery 配置

文件: `app/celery_app.py`

```python
app = Celery('shortdrama_ai')
app.config_from_object({
    'broker_url': 'redis://localhost:6379/0',
    'result_backend': 'redis://localhost:6379/1',
    'task_routes': {
        'app.tasks.video.*': {'queue': 'video'},
        'app.tasks.image.*': {'queue': 'image'},
        'app.tasks.text.*': {'queue': 'text'},
    },
    'worker_prefetch_multiplier': 1,
    'task_acks_late': True,
    'task_reject_on_worker_lost': True,
    'task_time_limit': 900,
    'task_soft_time_limit': 600,
    'broker_transport_options': {
        'priority_steps': list(range(10)),
        'queue_order_strategy': 'priority',
    },
})
```

---

## 5. 用户与计费系统

### 5.1 用户等级

| 能力 | Free | Pro | Enterprise |
|------|------|-----|------------|
| 月积分 | 100 | 2000 | 20000 |
| 并发任务 | 2 | 10 | 50 |
| 视频/小时 | 5 | 50 | 200 |
| 图片/小时 | 20 | 200 | 1000 |
| 项目数 | 3 | 50 | 不限 |
| 存储 | 1GB | 50GB | 500GB |
| 队列优先级 | 5(最低) | 3 | 1(最高) |

### 5.2 认证流程

```
注册: POST /api/auth/register → JWT + 赠送50积分
登录: POST /api/auth/login → JWT access_token + refresh_token
API Key: Authorization: Bearer sk_live_xxxxx → hash查表 → 注入user上下文
```

### 5.3 积分预扣模式

```
请求进来 → 按操作类型查 credit_pricing → 预扣积分(锁行)
  ↓
任务执行
  ↓
成功 → 扣实际消耗, 退还多余预扣
失败 → 全额退还预扣
```

---

## 6. API 变更

### 6.1 新增端点

```
POST   /api/auth/register
POST   /api/auth/login
POST   /api/auth/refresh
GET    /api/auth/me

POST   /api/keys
GET    /api/keys
DELETE /api/keys/{key_id}

GET    /api/credits
GET    /api/credits/transactions
GET    /api/credits/pricing

GET    /api/tasks
GET    /api/tasks/{task_id}
POST   /api/tasks/{task_id}/cancel

WS     /ws/tasks              (实时任务状态推送)
```

### 6.2 现有端点改造

所有现有端点不变路径，但：
- 加鉴权中间件 (注入 user_id)
- 数据按 user_id 隔离
- 异步操作返回 task_id (HTTP 202) 而非阻塞等待

改造示例 — `POST /api/batch/generate-videos`:
```
之前: 同步阻塞, 等所有视频生成完才返回
之后:
  1. 鉴权 → user_id
  2. 预扣积分 (N个视频 × 单价)
  3. 创建父任务 + N个子任务
  4. 入队 Celery
  5. 立即返回 {task_id, child_task_ids, status: "queued"}
  6. 客户端连 WebSocket 接收进度
```

### 6.3 WebSocket 协议

```json
// 服务端 → 客户端
{"type": "task_update", "task_id": "uuid", "status": "running", "progress": 45, "stage_text": "Polling Seedance..."}
{"type": "task_complete", "task_id": "uuid", "result": {...}}
{"type": "task_failed", "task_id": "uuid", "error": "..."}

// 客户端 → 服务端
{"type": "subscribe", "task_ids": ["uuid1", "uuid2"]}
{"type": "ping"}
```

---

## 7. 部署架构

```
Docker Compose (开发) / Kubernetes (生产)
├── api-server ×N (FastAPI, 无状态, 水平扩缩)
├── worker-video ×M (Celery, -Q video, 按key数扩缩)
├── worker-image ×M (Celery, -Q image)
├── worker-text ×M (Celery, -Q text)
├── celery-beat ×1 (定时任务: 重置计数器/过期任务/月度积分)
├── postgresql (主+只读副本)
├── redis (集群模式, 队列+缓存+pub/sub)
└── nginx (反向代理+负载均衡+SSL)
```

---

## 8. 分阶段实施路径

### Phase 1: 基础设施 (第1-2周)

**目标:** 加 PostgreSQL + Redis + Celery，不改用户体验

| 改动 | 文件 |
|------|------|
| DB 迁移到 PostgreSQL | `app/db.py` → 重写为 SQLAlchemy async |
| 迁移脚本 | `scripts/migrate_to_pg.py` 新建 |
| Redis 连接 | `app/redis_client.py` 新建 |
| Celery 配置 | `app/celery_app.py` 新建 |
| 任务定义 | `app/tasks/video_tasks.py` 新建 |
| 任务定义 | `app/tasks/image_tasks.py` 新建 |
| 替换 executor | `app/worker.py` → 改为 Celery dispatch |
| 替换 job_registry | `app/services/job_registry.py` → DB-backed |
| 本地开发环境 | `docker-compose.yml` 新建 |
| DB schema | `alembic/` 目录新建 |

**验证:** 现有 API 行为不变，但后台已走 Celery 队列。

### Phase 2: 多租户 (第3-4周)

**目标:** 加用户系统、数据隔离

| 改动 | 文件 |
|------|------|
| 用户表 + 认证 | `app/middleware/auth.py` 新建 |
| 注册/登录 API | `app/routes/auth.py` 新建 |
| API Key 管理 | `app/routes/keys.py` 新建 |
| 数据隔离 | 所有查询加 `WHERE user_id = ?` |
| 现有表加 user_id | Alembic migration |

**验证:** 注册 → 登录 → 创建项目 → 生成视频，全程带鉴权。

### Phase 3: 计费与限流 (第5-6周)

**目标:** 积分系统、限流、优先级队列

| 改动 | 文件 |
|------|------|
| 积分系统 | `app/services/credits.py` 新建 |
| 限流中间件 | `app/middleware/rate_limit.py` 新建 |
| Key Pool | `app/services/key_pool.py` 新建 |
| 优先级队列 | Celery priority 配置 |
| WebSocket | `app/ws/task_updates.py` 新建 |

**验证:** Free 用户超限被拒，Pro 用户优先处理，积分正确扣减。

### Phase 4: 生产就绪 (第7-8周)

**目标:** 监控、告警、自动扩缩、容灾

| 改动 | 说明 |
|------|------|
| 健康检查 | `/health` 含 DB/Redis/Worker 状态 |
| Prometheus metrics | 队列深度、worker 负载、API 延迟 |
| 自动扩缩 | K8s HPA 按队列深度扩 worker |
| 死信处理 | 管理后台查看/重试死信任务 |
| 备份恢复 | PostgreSQL WAL 归档 + 定时快照 |

---

## 9. 关键文件结构 (最终态)

```
app/
├── celery_app.py              # Celery 实例配置
├── redis_client.py            # Redis 连接池
├── db.py                      # SQLAlchemy async engine (替代 SQLite)
├── middleware/
│   ├── auth.py                # JWT/API Key 鉴权
│   ├── rate_limit.py          # Redis 滑动窗口限流
│   └── credits.py             # 积分预扣中间件
├── routes/
│   ├── auth.py                # 注册/登录/刷新
│   ├── keys.py                # API Key CRUD
│   ├── credits.py             # 积分查询/交易历史
│   └── tasks.py               # 任务查询/取消
├── tasks/
│   ├── video_tasks.py         # Celery 视频生成任务
│   ├── image_tasks.py         # Celery 图片生成任务
│   ├── text_tasks.py          # Celery 文本任务
│   └── admin_tasks.py         # 定时任务(重置/过期/月度)
├── services/
│   ├── key_pool.py            # API Key 池管理
│   ├── credits.py             # 积分预扣/退还/查询
│   ├── ref_resolver.py        # (现有) 引用解析
│   ├── workbench_orchestrator.py # (现有) 编排层
│   ├── seedance.py            # (现有) 视频生成
│   └── seedream.py            # (现有) 图片生成
├── ws/
│   └── task_updates.py        # WebSocket 实时推送
├── main.py                    # (现有, 改造: 加中间件, 异步化)
└── config.py                  # (扩展: 加 Redis/PG/Celery 配置)

docker-compose.yml             # 本地开发: PG + Redis + Worker
alembic/                       # DB 迁移
scripts/
├── migrate_to_pg.py           # SQLite → PostgreSQL 迁移
└── verify_repo.py             # (现有)
```

---

## 10. 验证方式

每个 Phase 完成后的验证:

- Phase 1: `docker-compose up` → 现有 API 全部通过 → batch 走 Celery 队列
- Phase 2: 注册用户 → 登录 → 创建项目 → 无法访问他人项目
- Phase 3: Free 用户连续生成6个视频 → 第6个被 429 → Pro 用户不受限
- Phase 4: 杀掉一个 worker → 任务自动重分配 → 无数据丢失
