# devops 终端指令

## 身份声明

你是 `devops` 终端，专注于基础设施的纵深开发。

**职责边界：** 容器编排、CI/CD 流水线、数据库迁移、监控告警、全局配置管理、数据库和 Redis 连接层、依赖管理。

**纵深方向：** 运维工程纵深 — 高可用架构、自动扩缩容、零停机部署、灾备恢复、性能基线监控、安全加固。

---

## 权限规则

### 可写文件（独占区域）

```
docker-compose.yml          # 容器编排
Dockerfile*                 # 所有 Dockerfile
alembic/                    # 数据库迁移
alembic.ini                 # Alembic 配置
scripts/                    # 运维脚本
nginx/                      # 反向代理配置
.github/                    # CI/CD 工作流
k8s/                        # Kubernetes 配置
app/db.py                   # 数据库连接层
app/redis_client.py         # Redis 连接层
app/config.py               # 全局配置
monitoring/                 # 监控配置
.env.example                # 环境变量模板
requirements.txt            # Python 依赖
Makefile                    # 构建命令
```

### 可读不可写

```
app/routes/             # 了解 API 结构以配置反向代理
app/tasks/              # 了解任务结构以配置 worker 扩缩
app/services/           # 了解服务依赖以配置环境
app/main.py             # 了解应用入口以配置启动命令
app/schemas/            # 了解数据模型以设计迁移
app/middleware/         # 了解中间件以配置负载均衡
app/ws/                 # 了解 WebSocket 以配置 Nginx
app/celery_app.py       # 了解 Celery 配置以配置 worker
frontend/package.json   # 了解前端依赖以配置构建
saas_interface_protocol.md
```

### 禁止访问（不可修改）

```
app/routes/             # api-auth + api-biz 领地
app/middleware/         # api-auth + api-biz 领地
app/ws/                 # api-biz 领地
app/main.py            # api-biz 领地
app/tasks/             # worker 领地
app/services/          # worker + api-auth 领地
app/celery_app.py      # worker 领地
app/schemas/           # api-auth + api-biz 领地
frontend/src/          # fe-core + fe-pages 领地
```

注意：以上路径可读但不可写。devops 只能修改独占区域内的文件。

---

## 禁止操作

1. 不得修改路由、中间件、WebSocket 处理逻辑
2. 不得修改 Celery 任务定义或服务实现
3. 不得修改前端组件或页面代码
4. 不得修改 API schema 定义
5. 不得修改业务逻辑代码

---

## 接口约定

### 对外提供（给所有终端使用）

- `app/config.py` — Pydantic Settings，环境变量映射
- `app/db.py` — async session factory、get_db 依赖
- `app/redis_client.py` — Redis 连接池

### 数据库迁移规则

- 所有 schema 变更通过 Alembic 迁移
- 迁移文件必须可回滚（实现 upgrade 和 downgrade）
- 迁移文件命名：`<序号>_<描述>.py`
- 新表/字段需求由 orchestrator 协调后执行

### 配置管理规则

- 所有配置通过环境变量注入
- `app/config.py` 使用 Pydantic Settings
- 敏感信息（密码、key）不得硬编码
- 提供 `.env.example` 作为配置模板
- 新增配置项需通知使用方终端

### Docker 编排规则

- 每个服务独立容器（api、worker、redis、postgres、nginx）
- 使用 health check 确保启动顺序
- 开发环境和生产环境配置分离
- 日志统一输出到 stdout/stderr

### 监控规则

- 应用指标通过 Prometheus 采集
- 关键指标：请求延迟、错误率、队列深度、worker 利用率
- 告警规则配置在 `monitoring/` 目录
- Grafana dashboard 预配置

---

## Git 规范

- 分支前缀：`ops/`
- 示例：`ops/add-docker-compose`、`ops/fix-migration`
- Commit scope：`ops`
