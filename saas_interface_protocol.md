# SaaS 对接接口协议

> 本文件是新电脑 SaaS 系统开发时的对接契约。
> 当前系统已在所有关键入口预留 `user_id` 参数，SaaS 系统只需通过鉴权中间件注入即可。

---

## 1. 预留接口总览

| 模块 | 函数/端点 | 预留参数 | 当前行为 | SaaS接入后行为 |
|------|----------|----------|----------|---------------|
| crud.py | `create_project()` | `user_id=None` | 忽略 | 写入 projects.user_id |
| crud.py | `list_projects()` | `user_id=None` | 返回全部 | `WHERE user_id=?` 过滤 |
| crud.py | `create_asset()` | `user_id=None` | 忽略 | 写入 assets.user_id |
| crud.py | `list_assets()` | `user_id=None` | 返回全部 | `WHERE user_id=?` 过滤 |
| crud.py | `upsert_shot_row()` | `user_id=None` | 忽略 | 写入 shot_rows.user_id |
| crud.py | `list_shot_rows()` | `user_id=None` | 返回全部 | `WHERE user_id=?` 过滤 |
| job_registry.py | `create_job()` | `user_id=""` | 忽略 | 写入 Job.user_id |
| job_registry.py | `Job` dataclass | `user_id: str` | 空字符串 | 真实用户ID |
| main.py | `BatchGenerateImagesRequest` | `user_id=None` | 忽略 | 传入鉴权用户 |
| main.py | `BatchGenerateVideosRequest` | `user_id=None` | 忽略 | 传入鉴权用户 |

---

## 2. 融合方式

SaaS 系统开发完成后，融合步骤：

### Step 1: 加鉴权中间件

```python
# app/middleware/auth.py
from fastapi import Request, HTTPException

async def auth_middleware(request: Request, call_next):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(401, "missing token")
    user = verify_token(token)  # JWT 或 API Key 查表
    request.state.user_id = user.user_id
    request.state.user_tier = user.tier
    return await call_next(request)
```

### Step 2: 路由层注入 user_id

```python
# 改造示例: POST /api/projects
@app.post("/api/projects")
def create_project_endpoint(payload: ..., request: Request):
    user_id = request.state.user_id  # 从中间件获取
    project_id = crud.create_project(
        input_path=payload.input_path,
        name=payload.name,
        user_id=user_id,  # 传入预留参数
    )
    return {"project_id": project_id}
```

### Step 3: crud 层启用过滤

```python
# 当 user_id 不为 None 时，加 WHERE 条件
def list_projects(*, user_id: str | None = None):
    with get_conn() as conn:
        if user_id:
            rows = conn.execute(
                "SELECT ... FROM projects WHERE user_id=? ORDER BY id DESC",
                (user_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT ... FROM projects ORDER BY id DESC"
            ).fetchall()
    return [dict(r) for r in rows]
```

---

## 3. 数据库迁移

SaaS 系统需要在现有表上加 `user_id` 列：

```sql
-- PostgreSQL 迁移（从 SQLite 迁移后执行）
ALTER TABLE projects ADD COLUMN user_id BIGINT REFERENCES users(id);
ALTER TABLE assets ADD COLUMN user_id BIGINT REFERENCES users(id);
ALTER TABLE shot_rows ADD COLUMN user_id BIGINT;

-- 历史数据归属默认管理员
UPDATE projects SET user_id = 1 WHERE user_id IS NULL;
UPDATE assets SET user_id = 1 WHERE user_id IS NULL;
UPDATE shot_rows SET user_id = 1 WHERE user_id IS NULL;

-- 之后设为 NOT NULL
ALTER TABLE projects ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE assets ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE shot_rows ALTER COLUMN user_id SET NOT NULL;
```

---

## 4. 任务队列对接协议

### 4.1 当前系统提交任务的方式

```python
# 当前: executor.submit (fire-and-forget)
from app.worker import executor
executor.submit(_run_task)
```

### 4.2 SaaS 系统替换为

```python
# SaaS: Celery 异步任务
from app.celery_app import celery_app

@celery_app.task(bind=True, queue='video')
def generate_video_task(self, task_id: str, user_id: str, payload: dict):
    ...

# 调用方式
task = generate_video_task.apply_async(
    args=[task_id, user_id, payload],
    priority=get_user_priority(user_id),
)
```

### 4.3 任务状态回调

SaaS 系统需要实现的回调接口（Worker 完成后调用）：

```python
def on_task_complete(task_id: str, result: dict):
    """更新 tasks 表 + 发布 Redis pub/sub + 扣积分"""
    
def on_task_failed(task_id: str, error: str, retry: bool):
    """更新 tasks 表 + 决定重试或死信 + 退积分"""
```

---

## 5. Key Pool 对接协议

### 5.1 当前系统获取 key 的方式

```python
# app/config.py — 单 key
SEEDANCE_API_KEY = env_first("SEEDANCE_API_KEY", "ARK_API_KEY")
```

### 5.2 SaaS 系统替换为

```python
# app/services/key_pool.py
from app.services.key_pool import key_pool

key_name, api_key = key_pool.acquire(service="seedance")
try:
    result = call_seedance(api_key, ...)
finally:
    key_pool.release(key_name)
```

### 5.3 Key Pool 需要实现的接口

```python
class KeyPool:
    def acquire(self, service: str) -> tuple[str, str]:
        """返回 (key_name, decrypted_api_key)，无可用 key 抛 BackpressureError"""
        
    def release(self, key_name: str) -> None:
        """释放 key 并发计数"""
        
    def report_error(self, key_name: str, error_type: str) -> None:
        """报告错误，触发冷却"""
```

---

## 6. 积分对接协议

### 6.1 积分操作接口

```python
class CreditService:
    def check_balance(self, user_id: str, operation: str, quantity: int = 1) -> bool:
        """检查余额是否足够"""
        
    def reserve(self, user_id: str, operation: str, quantity: int = 1) -> str:
        """预扣积分，返回 transaction_id。余额不足抛 InsufficientCreditsError"""
        
    def charge(self, transaction_id: str, actual_amount: int | None = None) -> None:
        """确认扣费（可调整实际金额）"""
        
    def refund(self, transaction_id: str) -> None:
        """退还预扣积分"""
```

### 6.2 操作定价表

| operation | credits | 说明 |
|-----------|---------|------|
| video_gen_5s | 10 | 5秒视频 |
| video_gen_8s | 15 | 8秒视频 |
| video_gen_10s | 20 | 10秒视频 |
| image_gen | 2 | 单张图片 |
| llm_refine | 1 | prompt优化 |
| llm_director_chat | 1 | 导演对话 |
| pipeline_analysis | 5 | 视频分析 |

---

## 7. 限流对接协议

### 7.1 限流检查接口

```python
class RateLimiter:
    def check(self, user_id: str, resource: str) -> tuple[bool, dict]:
        """
        返回 (allowed, info)
        info = {"remaining": 3, "reset_at": 1715400000, "limit": 5}
        """
        
    def consume(self, user_id: str, resource: str) -> None:
        """消费一次配额"""
```

### 7.2 限流资源类型

| resource | 含义 | 窗口 |
|----------|------|------|
| concurrent_tasks | 同时执行的任务数 | 实时 |
| video_gen | 视频生成次数 | 1小时 |
| image_gen | 图片生成次数 | 1小时 |
| api_calls | API调用总次数 | 1分钟 |

---

## 8. WebSocket 对接协议

### 8.1 连接

```
WS /ws/tasks?token=<jwt_token>
```

### 8.2 服务端推送消息格式

```json
{"type": "task_update", "task_id": "uuid", "status": "running", "progress": 45, "stage_text": "生成中..."}
{"type": "task_complete", "task_id": "uuid", "result": {"url": "https://..."}}
{"type": "task_failed", "task_id": "uuid", "error": "policy violation", "credits_refunded": 10}
```

### 8.3 客户端消息

```json
{"type": "subscribe", "task_ids": ["uuid1", "uuid2"]}
{"type": "unsubscribe", "task_ids": ["uuid1"]}
{"type": "ping"}
```

---

## 9. 存储隔离协议

### 9.1 TOS 路径规则

```
当前: shortdrama-ai/{project_id}/...
SaaS: shortdrama-ai/{user_id}/{project_id}/...
```

### 9.2 本地存储路径规则

```
当前: storage/projects/{project_id}/...
SaaS: storage/users/{user_id}/{project_id}/...
```

---

## 10. 开发检查清单

新电脑开发 SaaS 系统时，按此顺序实现：

- [ ] PostgreSQL 部署 + 建表（第2章 SQL）
- [ ] Redis 部署
- [ ] 用户注册/登录 API
- [ ] JWT 鉴权中间件
- [ ] Celery + Worker 基础框架
- [ ] Key Pool 管理器
- [ ] 积分系统（预扣/扣费/退还）
- [ ] 限流中间件
- [ ] WebSocket 实时推送
- [ ] 与本项目融合（注入 user_id 到预留参数）
- [ ] 数据迁移脚本（SQLite → PostgreSQL）
- [ ] docker-compose.yml 一键启动

---

## 11. 本项目当前代码位置索引

| 功能 | 文件 | 说明 |
|------|------|------|
| 项目 CRUD | app/crud.py:10-48 | create/list/get/update project |
| 资产 CRUD | app/crud.py:446-503 | create/list/get/update/delete asset |
| 脚本行 CRUD | app/crud.py:349-443 | upsert/get/list/update shot_row |
| 批量生成图 | app/main.py (搜 batch_generate_images) | 含并发控制+审计 |
| 批量生成视频 | app/main.py (搜 batch_generate_videos) | 含Policy降级 |
| Job Registry | app/services/job_registry.py | 内存任务跟踪 |
| Seedance 调用 | app/services/seedance.py | 视频生成+轮询 |
| Seedream 调用 | app/services/seedream.py | 图片生成 |
| TOS 上传 | app/services/tos.py | 对象存储 |
| 全局配置 | app/config.py | API key + 模型名 |
| Worker | app/worker.py | ThreadPoolExecutor(4) |
| Ref Resolver | app/services/ref_resolver.py | 引用解析+pack |
| Orchestrator | app/services/workbench_orchestrator.py | 工作流编排 |
