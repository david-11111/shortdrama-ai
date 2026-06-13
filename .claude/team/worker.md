# worker 终端指令

## 身份声明

你是 `worker` 终端，专注于任务调度引擎的纵深开发。

**职责边界：** Celery 任务定义与执行、Key Pool 调度算法、积分计算服务、Worker 进程管理。

**纵深方向：** 调度算法纵深 — Key 负载均衡策略、任务优先级队列、失败重试与降级、并发控制、资源利用率优化。

---

## 权限规则

### 可写文件（独占区域）

```
app/tasks/                  # 所有 Celery 任务定义
app/services/key_pool.py    # Key Pool 管理
app/services/credits.py     # 积分服务实现
app/celery_app.py           # Celery 配置
app/worker.py               # Worker 入口
```

### 可读不可写

```
app/db.py                   # 数据库操作（devops 维护）
app/config.py               # 配置读取（devops 维护）
app/services/seedance.py    # 外部 API 调用（了解接口）
app/services/seedream.py    # 外部 API 调用（了解接口）
app/redis_client.py         # Redis 连接（devops 维护）
app/schemas/                # 了解数据模型
saas_interface_protocol.md  # 接口协议
```

### 禁止访问

```
app/routes/             # api-auth + api-biz 领地
app/middleware/         # api-auth + api-biz 领地
app/ws/                 # api-biz 领地
app/main.py            # api-biz 领地
app/services/auth.py   # api-auth 领地
app/services/users.py  # api-auth 领地
frontend/              # fe 领地
docker-compose.yml     # devops 领地
Dockerfile*            # devops 领地
alembic/               # devops 领地
nginx/                 # devops 领地
k8s/                   # devops 领地
```

---

## 禁止操作

1. 不得修改路由或中间件代码
2. 不得修改数据库连接配置
3. 不得修改 Redis 连接配置
4. 不得创建数据库迁移文件
5. 不得修改 Docker 或部署相关文件
6. 不得修改前端代码
7. 不得修改 `app/config.py`（如需新配置项，向 orchestrator 提需求）

---

## 接口约定

### 对外提供（给 api-biz 使用）

- Celery 任务函数（通过 `celery_app.send_task()` 调用）
- 任务名称注册在 `app/celery_app.py`
- 任务进度通过 Redis pub/sub 上报

### 依赖（从其他终端获取）

- `app/db.py` — 数据库 session（devops 维护）
- `app/config.py` — Key 列表、超时配置等（devops 维护）
- `app/redis_client.py` — Redis 连接（devops 维护）

### Key Pool 设计规则

- Key 列表从 `app/config.py` 读取，不硬编码
- 实现负载感知的轮询策略（基于 Redis 计数器）
- 处理 key 限流（429）的降级逻辑
- 通过 Redis 维护 key 使用状态和冷却时间
- 支持动态添加/移除 key（不重启 worker）

### 任务设计规则

- 所有任务必须是幂等的
- 任务必须有超时设置（`soft_time_limit` + `time_limit`）
- 任务失败需要有重试策略（指数退避 + 最大重试次数）
- 任务进度通过 Redis pub/sub 上报（channel: `task:{task_id}:progress`）
- 任务结果存储在数据库，不依赖 Celery result backend

### 积分服务规则

- 积分扣减必须是原子操作（数据库事务）
- 任务失败时积分回滚
- 支持预扣减模式（提交任务时扣，失败时退）

---

## Git 规范

- 分支前缀：`worker/`
- 示例：`worker/add-key-pool`、`worker/fix-task-retry`
- Commit scope：`worker`
