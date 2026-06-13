# T11 指令 — api-biz 终端

## 你的身份

你是 `api-biz` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 任务目标

为 API 层添加生产必需的三个组件：CORS、结构化日志、全局异常处理。

## 分支

```bash
git checkout -b api/phase4-production-hardening
```

## 需要修改的文件

### 1. `app/main.py` — 添加 CORS + 全局异常处理 + 日志

在现有 `app = FastAPI(...)` 之后添加：

```python
import logging
import traceback

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

# --- 结构化日志 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("app")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # Vite dev
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 全局异常处理 ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception: %s %s — %s",
        request.method,
        request.url.path,
        str(exc),
    )
    logger.debug(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc) if settings.app_debug else None},
    )
```

### 2. `app/main.py` — 添加 startup 事件日志

```python
@app.on_event("startup")
async def on_startup():
    logger.info("ShortDrama AI SaaS API starting — env=%s debug=%s", settings.app_env, settings.app_debug)

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("ShortDrama AI SaaS API shutting down")
```

### 3. CORS `allow_origins` 支持环境变量

在 `app/config.py` 的 `Settings` 类中添加：

```python
cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
```

然后 `main.py` 中用 `settings.cors_origins.split(",")` 替代硬编码列表。

## 注意事项

- 不要删除或修改现有的路由和端点逻辑
- CORS 中间件必须在路由注册之前添加（FastAPI 中间件按添加顺序的逆序执行）
- `allow_credentials=True` 是必须的，因为前端会发送 Authorization header
- 全局异常处理只捕获未被路由自身处理的异常，不影响已有的 HTTPException

## 验收标准

1. 前端 `http://localhost:3000` 能跨域调用 `http://localhost:8000/api/*`
2. 未捕获异常返回 `{"error": "Internal server error"}` 而非裸 traceback
3. 启动时控制台输出结构化日志
4. `CORS_ORIGINS` 环境变量可配置允许的域名

## 完成后

告诉 orchestrator：T11 完成，列出修改的文件。
