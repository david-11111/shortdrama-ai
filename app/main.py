import logging
import traceback

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.middleware.audit import AdminAuditMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.celery_app import celery_app  # noqa: F401
from app.config import get_settings
from app.db import AsyncSessionLocal, engine, get_db
from app.middleware.auth import get_current_user
from app.middleware.credits import reserve_credits
from app.middleware.rate_limit import check_concurrent_limit, check_rate_limit
from app.redis_client import redis_client
from app.routes import api_router
from app.schemas.tasks import BatchTaskSubmitResponse, TaskSubmitResponse
from app.services.cost_guard import assert_cost_guard
from app.services.credits import credit_service
from app.services.director_preflight import analyze_shot_risk
from app.services.infrastructure_preflight import guard_infrastructure_preflight
from app.services.production_entrypoint import direct_generation_block_detail
from app.services.task_submission import submit_batch_tasks, submit_single_task
from app.ws.task_updates import ws_task_updates
from monitoring.health import install_monitoring

# --- 缁撴瀯鍖栨棩蹇?---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("app")

settings = get_settings()


def _extract_batch_items(payload: dict) -> list[dict]:
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise HTTPException(400, "items must be a list")
    if not items:
        raise HTTPException(400, "items cannot be empty")
    if len(items) > settings.batch_max_items:
        raise HTTPException(400, f"items cannot exceed {settings.batch_max_items}")
    if not all(isinstance(item, dict) for item in items):
        raise HTTPException(400, "each item must be an object")
    return items


def _guard_generation_preflight(items: list[dict], *, target: str) -> None:
    blocked: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        shot_row = item.get("shot_row") if isinstance(item.get("shot_row"), dict) else item
        project_goal = str(item.get("project_goal") or item.get("goal") or "")
        report = analyze_shot_risk(shot_row, project_goal=project_goal)
        should_block = report.get("risk_level") == "blocked"
        if target == "video" and report.get("risk_level") == "warning" and not shot_row.get("selected_image"):
            should_block = True
        if not should_block:
            continue
        blocked.append({
            "shot_index": shot_row.get("shot_index") or shot_row.get("index"),
            "risk_level": report.get("risk_level"),
            "risks": report.get("risks", []),
            "suggestions": report.get("suggestions", []),
            "safe_prompt": report.get("safe_prompt", ""),
        })
    if blocked:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "director_preflight_blocked",
                "message": "Generation preflight failed. Please fix blocked shots before submitting.",
                "blocked_shots": blocked,
            },
        )

app = FastAPI(
    title="ShortDrama AI SaaS",
    version="0.1.0",
    debug=settings.app_debug,
)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Request-ID ---
app.add_middleware(RequestIDMiddleware)

# --- 绠＄悊绔璁′腑闂翠欢 ---
app.add_middleware(AdminAuditMiddleware)


def _public_http_error(detail: object) -> tuple[str, str, dict | None]:
    if isinstance(detail, dict):
        code = str(detail.get("code") or detail.get("error") or "request_error")
        user_message = str(detail.get("user_message") or "").strip()
        if not user_message:
            message = str(detail.get("message") or "").strip()
            user_message = _friendly_error_message(code=code, message=message, detail=detail)
        return code, user_message, detail
    message = str(detail or "请求处理失败")
    return "request_error", _friendly_error_message(code="request_error", message=message, detail={}), None


def _friendly_error_message(*, code: str, message: str, detail: dict) -> str:
    text = f"{code} {message}".lower()
    if "active_tasks" in text or "already has active tasks" in text:
        count = detail.get("active_task_count") or 1
        return f"当前已有 {count} 个任务正在执行，先等待完成或刷新成果区后再继续。"
    if "cancelled" in text:
        return "当前 run 已取消，不能继续执行。"
    if "already completed" in text:
        return "当前 run 已完成，如需继续请创建新的后续任务。"
    if "budget" in text or "credits" in text or "insufficient" in text:
        return "本次操作预算不足，请调整范围或提高预算后再继续。"
    if "provider" in text and ("saturated" in text or "rate" in text or "429" in text):
        return "Provider 暂时繁忙，任务已进入等待恢复状态。"
    if "preflight" in text:
        return "生成前检查未通过，请先处理被拦截的镜头。"
    return message or "请求没有执行，请检查当前阶段后再试。"


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code, user_message, debug_detail = _public_http_error(exc.detail)
    headers = dict(getattr(exc, "headers", None) or {})
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        headers["X-Request-ID"] = str(request_id)
    content: dict[str, object] = {
        "detail": user_message,
        "error": {
            "code": code,
            "message": user_message,
        },
    }
    if settings.app_debug and debug_detail is not None:
        content["debug"] = debug_detail
    return JSONResponse(status_code=exc.status_code, content=content, headers=headers or None)


# --- 鍏ㄥ眬寮傚父澶勭悊 ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.error(
        "Unhandled exception: %s %s request_id=%s 鈥?%s",
        request.method,
        request.url.path,
        request_id,
        str(exc),
    )
    logger.debug(traceback.format_exc())
    headers = {"X-Request-ID": str(request_id)} if request_id else None
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc) if settings.app_debug else None},
        headers=headers,
    )


# --- Lifecycle ---
@app.on_event("startup")
async def on_startup():
    logger.info("ShortDrama AI SaaS API starting 鈥?env=%s debug=%s", settings.app_env, settings.app_debug)


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("ShortDrama AI SaaS API shutting down")
    try:
        await redis_client.close()
        await redis_client.connection_pool.disconnect()
    except Exception:
        logger.exception("Error closing Redis connection")
    try:
        await engine.dispose()
    except Exception:
        logger.exception("Error disposing database engine")
    logger.info("Shutdown complete")


# 娉ㄥ唽涓氬姟璺敱
install_monitoring(app)
app.include_router(api_router)


# --- 鎵归噺鐢熸垚绔偣锛堝紓姝ユ淳鍙戯級 ---

@app.post("/api/batch/generate-videos", status_code=202, response_model=BatchTaskSubmitResponse)
async def batch_generate_videos(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    瀹屾暣娴佺▼: 閴存潈 鈫?骞跺彂妫€鏌?鈫?闄愭祦妫€鏌?鈫?绉垎棰勬墸 鈫?娲惧彂浠诲姟
    """
    await guard_infrastructure_preflight("video_gen")
    user_id = current_user["id"]
    user_tier = current_user["tier"]
    items = _extract_batch_items(payload)
    quantity = len(items)

    _guard_generation_preflight(items, target="video")

    # 1. 骞跺彂浠诲姟鏁版鏌?
    await check_concurrent_limit(user_id, user_tier, db)

    # 2. 闄愭祦妫€鏌ワ紙瑙嗛鐢熸垚棰戠巼锛?
    await check_rate_limit(user_id, user_tier, "video_gen", db)

    # 3. 涓烘瘡涓瓙浠诲姟鐙珛棰勬墸绉垎锛堜换涓€澶辫触鍒欓€€杩樺凡鎵ｏ級
    operation = "video_gen_5s"
    unit_price = await credit_service.get_price(operation)
    await assert_cost_guard(db, user_id=user_id, credits_to_reserve=quantity * unit_price)
    priority_map = {"free": 5, "pro": 3, "enterprise": 1}
    priority = priority_map.get(user_tier, 5)

    def _video_payload(item: dict, _index: int) -> dict:
        task_payload = dict(item)
        task_payload.setdefault("provider", payload.get("provider", "ltx2.3"))
        return task_payload

    submission = await submit_batch_tasks(
        user_id=user_id,
        operation=operation,
        unit_price=unit_price,
        task_type="video_gen",
        celery_task_name="app.tasks.video_tasks.generate_video_task",
        queue="video",
        priority=priority,
        items=items,
        payload_factory=_video_payload,
        reserve_func=reserve_credits,
    )

    return BatchTaskSubmitResponse(
        parent_task_id=submission.parent_task_id,
        child_task_ids=submission.child_task_ids,
        status="queued",
        total_credits_reserved=submission.total_credits_reserved,
        main_chain_path="platform_direct_task",
    )


@app.post("/api/batch/generate-images", status_code=202, response_model=BatchTaskSubmitResponse)
async def batch_generate_images(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    瀹屾暣娴佺▼: 閴存潈 鈫?骞跺彂妫€鏌?鈫?闄愭祦妫€鏌?鈫?绉垎棰勬墸 鈫?娲惧彂浠诲姟
    """
    await guard_infrastructure_preflight("image_gen")
    user_id = current_user["id"]
    user_tier = current_user["tier"]
    items = _extract_batch_items(payload)
    quantity = len(items)

    _guard_generation_preflight(items, target="image")

    # 1. 骞跺彂浠诲姟鏁版鏌?
    await check_concurrent_limit(user_id, user_tier, db)

    # 2. 闄愭祦妫€鏌ワ紙鍥剧墖鐢熸垚棰戠巼锛?
    await check_rate_limit(user_id, user_tier, "image_gen", db)

    # 3. 涓烘瘡涓瓙浠诲姟鐙珛棰勬墸绉垎锛堜换涓€澶辫触鍒欓€€杩樺凡鎵ｏ級
    operation = "image_gen"
    unit_price = await credit_service.get_price(operation)
    await assert_cost_guard(db, user_id=user_id, credits_to_reserve=quantity * unit_price)
    priority_map = {"free": 5, "pro": 3, "enterprise": 1}
    priority = priority_map.get(user_tier, 5)

    submission = await submit_batch_tasks(
        user_id=user_id,
        operation=operation,
        unit_price=unit_price,
        task_type="image_gen",
        celery_task_name="app.tasks.image_tasks.generate_image_task",
        queue="image",
        priority=priority,
        items=items,
        reserve_func=reserve_credits,
    )

    return BatchTaskSubmitResponse(
        parent_task_id=submission.parent_task_id,
        child_task_ids=submission.child_task_ids,
        status="queued",
        total_credits_reserved=submission.total_credits_reserved,
        main_chain_path="platform_direct_task",
    )


@app.post("/api/tts/generate", status_code=202, response_model=TaskSubmitResponse)
async def generate_tts(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    TTS 璇煶鍚堟垚銆?
    payload: { text: str, voice?: str, speed?: float }
    """
    user_id = current_user["id"]
    user_tier = current_user["tier"]

    # 骞跺彂 + 闄愭祦妫€鏌?
    await check_concurrent_limit(user_id, user_tier, db)
    await check_rate_limit(user_id, user_tier, "tts_gen", db)

    # 绉垎棰勬墸
    tts_operation = "tts_synthesis"
    tts_price = await credit_service.get_price(tts_operation)
    await assert_cost_guard(db, user_id=user_id, credits_to_reserve=tts_price)

    # 娲惧彂浠诲姟
    priority_map = {"free": 5, "pro": 3, "enterprise": 1}
    priority = priority_map.get(user_tier, 5)

    submission = await submit_single_task(
        user_id=user_id,
        operation=tts_operation,
        unit_price=tts_price,
        task_type="tts",
        celery_task_name="app.tasks.tts_tasks.generate_tts_task",
        queue="text",
        priority=priority,
        payload=payload,
        reserve_func=reserve_credits,
    )

    return TaskSubmitResponse(
        task_id=submission.task_id,
        status="queued",
        message="TTS task submitted",
        main_chain_path="platform_direct_task",
    )


# --- WebSocket ---

@app.websocket("/ws/tasks")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(default="")):
    await ws_task_updates(websocket, token)

