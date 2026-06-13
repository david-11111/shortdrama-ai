# T10 指令 — devops 终端

## 你的身份

你是 `devops` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 任务目标

初始化 Git 仓库 + 创建 .gitignore + 首次提交。

## 具体步骤

### 1. 创建 `.gitignore`

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
.venv/
*.egg-info/
dist/
build/

# Environment
.env
.env.local
.env.*.local

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Node / Frontend
frontend/node_modules/
frontend/dist/

# Docker volumes
postgres_data/
redis_data/

# Logs
*.log
logs/

# Alembic
alembic/versions/__pycache__/

# Coverage
htmlcov/
.coverage
```

### 2. 初始化仓库并首次提交

```bash
cd "D:/20240313整理文件/Desktop/saas"
git init
git add .
git commit -m "feat: initial commit — Phase 1-3 complete

Infrastructure: PostgreSQL + Redis + Celery + Docker Compose
Backend: FastAPI async API + JWT/API Key auth + rate limiting + credits
Worker: Video/Image/Text tasks with Key Pool + charge/refund + dead letter
Frontend: Vue 3 + Vite + Pinia + login/register/dashboard/tasks pages"
```

### 3. 创建 develop 分支

```bash
git checkout -b develop
```

后续所有终端从 develop 拉分支，合并回 develop，最终 develop → main。

## 验收标准

1. `git log` 能看到首次提交
2. `.gitignore` 正确排除了 `__pycache__`、`node_modules`、`.env` 等
3. 当前在 `develop` 分支
4. `git status` 干净（无未跟踪文件）

## 完成后

告诉 orchestrator：T10 完成，确认当前分支和提交 hash。
