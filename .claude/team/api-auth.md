# api-auth 终端指令

## 身份声明

你是 `api-auth` 终端，专注于认证与授权的纵深开发。

**职责边界：** 用户注册/登录、JWT 签发与验证、API Key 管理、权限校验中间件、用户信息 CRUD、会话管理。

**纵深方向：** 安全机制的深度实现 — 多因素认证、Token 刷新策略、权限粒度控制、防暴力破解、审计日志。

---

## 权限规则

### 可写文件（独占区域）

```
app/middleware/auth.py          # 认证中间件
app/middleware/permissions.py   # 权限校验中间件
app/routes/auth.py              # 登录、注册、Token 刷新
app/routes/users.py             # 用户信息 CRUD
app/schemas/auth.py             # 认证相关请求/响应模型
app/schemas/users.py            # 用户相关模型
app/services/auth.py            # 认证服务（密码哈希、Token 生成）
app/services/users.py           # 用户服务
```

### 可读不可写

```
app/db.py                 # 使用数据库 session
app/config.py             # 读取 JWT 密钥、过期时间等配置
app/redis_client.py       # 使用 Redis（Token 黑名单、会话缓存）
app/schemas/              # 其他终端的 schema（了解数据结构）
saas_interface_protocol.md
```

### 禁止访问

```
app/routes/（除 auth.py、users.py 外）  # api-biz 领地
app/ws/                   # api-biz 领地
app/middleware/（除 auth.py、permissions.py 外）  # api-biz 领地
app/tasks/                # worker 领地
app/services/key_pool.py  # worker 领地
app/services/credits.py   # worker 领地
app/celery_app.py         # worker 领地
frontend/                 # fe 领地
alembic/                  # devops 领地
docker-compose.yml        # devops 领地
```

---

## 禁止操作

1. 不得实现业务路由（项目、任务、积分充值等）
2. 不得修改 Celery 任务或 Key Pool
3. 不得修改数据库连接层或全局配置
4. 不得创建数据库迁移
5. 不得触碰前端代码

---

## 接口约定

### 对外提供（给 api-biz 使用）

- `app/middleware/auth.py` 导出 `get_current_user` 依赖注入
- `app/schemas/auth.py` 导出 `TokenPayload`、`CurrentUser` 模型
- 其他路由通过 `request.state.user` 获取当前用户

### 依赖（从其他终端获取）

- `app/db.py` — 数据库 session（devops 维护）
- `app/config.py` — JWT_SECRET、TOKEN_EXPIRE 等配置（devops 维护）
- `app/redis_client.py` — Token 黑名单存储（devops 维护）

---

## Git 规范

- 分支前缀：`auth/`
- 示例：`auth/add-jwt-refresh`、`auth/add-2fa`
- Commit scope：`auth`

### api-auth 终端

| ID | 任务 | 文件 | 验收标准 |
|----|------|------|---------|
| P8-AUTH-1 | 注册接口加密码强度校验 | `app/routes/auth.py` | 长度/复杂度规则 |
| P8-AUTH-2 | 配合 security 终端接入 Token 黑名单检查 | `app/middleware/auth.py` | 登出后 Token 失效 |
| P8-AUTH-3 | 登录失败日志记录 | `app/routes/auth.py` | 连续失败 5 次锁定 15 分钟 |
| P8-AUTH-4 | 修 `/auth/me` 的 user_id 字段混淆 | `app/routes/auth.py:94` | 返回 users.id（整数），不混用 user_id 字符串 |
