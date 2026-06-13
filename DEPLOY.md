# ShortDrama AI SaaS 部署指南

## 系统要求

| 组件 | 最低版本 | 说明 |
|------|---------|------|
| Docker | 20.0+ | 容器运行时 |
| Docker Compose | v2.0+ | 服务编排 |
| RAM | 4GB+ | 建议生产环境 8GB+ |
| 磁盘 | 20GB+ | 含数据库和媒体文件存储 |

## 快速启动

```bash
# 1. 克隆项目
git clone <repo-url> && cd saas

# 2. 复制环境变量文件
cp .env.example .env

# 3. 编辑 .env，填写必要配置（见下方环境变量说明）
vim .env

# 4. 启动所有服务
docker-compose up -d

# 5. 查看服务状态
docker-compose ps
```

## 环境变量说明

### 数据库

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+asyncpg://postgres:postgres@postgres:5432/saas_db` |

### Redis

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `REDIS_URL` | Redis 连接地址 | `redis://redis:6379/0` |
| `CELERY_BROKER_URL` | Celery Broker | `redis://redis:6379/1` |
| `CELERY_RESULT_BACKEND` | Celery 结果后端 | `redis://redis:6379/2` |

### JWT 认证

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `JWT_SECRET` | JWT 签名密钥（生产环境必须修改） | 随机字符串 |
| `JWT_EXPIRE_MINUTES` | Access Token 过期时间（分钟） | `30` |
| `JWT_REFRESH_EXPIRE_DAYS` | Refresh Token 过期时间（天） | `7` |

### API Keys

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `ARK_API_KEYS` | 火山引擎 API Keys（逗号分隔） | `key1,key2` |

### 对象存储 (OSS)

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `OSS_ENDPOINT` | OSS 服务端点 | `https://tos-cn-beijing.volces.com` |
| `OSS_ACCESS_KEY` | 访问密钥 ID | - |
| `OSS_SECRET_KEY` | 访问密钥 Secret | - |
| `OSS_BUCKET` | 存储桶名称 | `shortdrama-ai` |
| `OSS_REGION` | 区域 | `cn-beijing` |
| `OSS_CDN_DOMAIN` | CDN 加速域名（可选） | `cdn.example.com` |

### 支付配置

| 变量名 | 说明 |
|--------|------|
| `WECHAT_APP_ID` | 微信应用 ID |
| `WECHAT_MCH_ID` | 微信商户号 |
| `WECHAT_API_KEY` | 微信 API 密钥 |
| `WECHAT_CERT_SERIAL` | 微信证书序列号 |
| `WECHAT_PRIVATE_KEY_PATH` | 微信私钥文件路径 |
| `WECHAT_NOTIFY_URL` | 微信支付回调地址 |
| `ALIPAY_APP_ID` | 支付宝应用 ID |
| `ALIPAY_PRIVATE_KEY` | 支付宝私钥 |
| `ALIPAY_PUBLIC_KEY` | 支付宝公钥 |
| `ALIPAY_NOTIFY_URL` | 支付宝回调地址 |
| `ALIPAY_RETURN_URL` | 支付宝前端跳转地址 |

### 应用配置

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `APP_ENV` | 运行环境 | `production` / `development` |
| `APP_DEBUG` | 调试模式 | `false` |
| `CORS_ORIGINS` | 允许的跨域来源（逗号分隔） | `https://your-domain.com` |

## 数据库迁移

```bash
# 执行迁移（容器内自动执行，也可手动触发）
docker-compose run --rm migrate

# 生成新的迁移文件
docker-compose run --rm api alembic revision --autogenerate -m "描述"

# 回滚一个版本
docker-compose run --rm api alembic downgrade -1
```

## 常用运维命令

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f api
docker-compose logs -f worker-video

# 重启单个服务
docker-compose restart api

# 扩容 worker（例如扩展视频处理 worker 到 3 个实例）
docker-compose up -d --scale worker-video=3

# 查看服务资源使用
docker stats

# 进入容器调试
docker-compose exec api bash

# 停止所有服务
docker-compose down

# 停止并清除数据卷（危险操作）
docker-compose down -v
```

## 生产部署注意事项

### HTTPS 配置

- 使用 Nginx 反向代理或云负载均衡器终止 TLS
- 推荐使用 Let's Encrypt 免费证书，配合 certbot 自动续期
- 确保 `WECHAT_NOTIFY_URL` 和 `ALIPAY_NOTIFY_URL` 使用 HTTPS

### 域名配置

- API 服务绑定域名，如 `api.your-domain.com`
- 配置 DNS 解析指向服务器 IP
- CDN 域名用于静态资源和媒体文件加速

### 备份策略

```bash
# 使用项目自带备份脚本
chmod +x scripts/backup.sh
./scripts/backup.sh

# 建议配置 crontab 每日自动备份
# 每天凌晨 3 点执行备份
0 3 * * * /path/to/project/scripts/backup.sh >> /var/log/backup.log 2>&1
```

- 数据库：每日全量备份，保留 7 天
- 媒体文件：依赖 OSS 自身的冗余存储
- 配置文件：纳入版本控制（敏感信息除外）

### 安全加固

- 修改所有默认密码（`JWT_SECRET`、数据库密码等）
- 限制数据库和 Redis 仅内网访问
- 启用防火墙，仅开放 80/443 端口
- 定期更新基础镜像

## 故障排查指南

### 服务无法启动

```bash
# 检查容器状态
docker-compose ps

# 查看失败容器的日志
docker-compose logs api

# 检查端口占用
netstat -tlnp | grep 8000
```

### 数据库连接失败

```bash
# 确认 PostgreSQL 容器健康
docker-compose exec postgres pg_isready

# 检查连接串是否正确
docker-compose exec api python -c "from app.config import get_settings; print(get_settings().database_url)"
```

### Redis 连接失败

```bash
# 确认 Redis 容器健康
docker-compose exec redis redis-cli ping

# 检查 Redis 内存使用
docker-compose exec redis redis-cli info memory
```

### Worker 任务堆积

```bash
# 查看队列长度
docker-compose exec redis redis-cli llen video
docker-compose exec redis redis-cli llen image
docker-compose exec redis redis-cli llen text

# 扩容对应 worker
docker-compose up -d --scale worker-video=3
```

### 健康检查

```bash
# 基础健康检查
curl http://localhost:8000/health

# 详细健康检查（含依赖服务状态）
curl http://localhost:8000/health/detailed
```
