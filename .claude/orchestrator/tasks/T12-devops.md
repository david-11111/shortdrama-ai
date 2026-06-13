# T12 指令 — devops 终端

## 你的身份

你是 `devops` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 任务目标

完善 Docker Compose 配置，使 `docker-compose up` 能跑通完整系统（含前端构建、Nginx 反代、Admin worker、Beat 调度器、自动迁移）。

## 分支

```bash
git checkout -b ops/phase4-docker-production
```

## 需要创建/修改的文件

### 1. `docker-compose.yml` — 补全缺失服务

在现有基础上添加：

```yaml
  # 数据库迁移（一次性任务）
  migrate:
    build:
      context: .
      dockerfile: Dockerfile
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy
    command: alembic upgrade head
    restart: "no"

  # Admin worker（处理 admin 队列 + default 队列）
  worker-admin:
    build:
      context: .
      dockerfile: Dockerfile
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: celery -A app.celery_app worker -Q admin,default -c 2 --pool=threads -l info

  # Beat 调度器
  beat:
    build:
      context: .
      dockerfile: Dockerfile
    env_file:
      - .env
    depends_on:
      redis:
        condition: service_healthy
    command: celery -A app.celery_app beat -l info

  # 前端构建 + Nginx 反代
  nginx:
    build:
      context: .
      dockerfile: Dockerfile.nginx
    ports:
      - "80:80"
    depends_on:
      - api
```

让 `api` 服务也依赖 `migrate`：
```yaml
  api:
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
```

### 2. `Dockerfile.nginx`（新建）

多阶段构建：先构建前端，再用 Nginx 服务静态文件 + 反代 API。

```dockerfile
# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Nginx
FROM nginx:alpine
COPY --from=frontend-build /app/dist /usr/share/nginx/html
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

### 3. `nginx/default.conf`（新建）

```nginx
server {
    listen 80;
    server_name _;

    # 前端静态文件
    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # API 反代
    location /api/ {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket 反代
    location /ws/ {
        proxy_pass http://api:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }

    # 健康检查
    location /health {
        proxy_pass http://api:8000;
    }
}
```

### 4. `.env.example` 更新

确保包含所有必需的环境变量：

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/saas_db
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
JWT_SECRET=change-me-in-production
JWT_EXPIRE_MINUTES=30
JWT_REFRESH_EXPIRE_DAYS=7
ARK_API_KEYS=your-key-1,your-key-2
APP_ENV=production
APP_DEBUG=false
CORS_ORIGINS=http://localhost
```

### 5. `Dockerfile` 优化

改为多阶段构建，减小镜像体积：

```dockerfile
FROM python:3.11-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

（当前已经够用，如果你觉得需要优化可以加 .dockerignore）

### 6. `.dockerignore`（新建）

```
frontend/node_modules
frontend/dist
__pycache__
*.pyc
.git
.env
.venv
venv
*.egg-info
```

## 验收标准

1. `docker-compose up --build` 能启动所有服务（postgres, redis, migrate, api, worker-video, worker-image, worker-text, worker-admin, beat, nginx）
2. 访问 `http://localhost` 能看到前端页面
3. 前端通过 Nginx 反代能调通 `/api/*` 和 `/ws/*`
4. `migrate` 服务执行完 alembic 后自动退出
5. Beat 调度器每 60s 触发 key-pool-refresh

## 完成后

告诉 orchestrator：T12 完成，列出创建/修改的文件清单。
