"""Health checks and Prometheus metrics for the API service.

Endpoints
---------
GET /health              — liveness probe (light, no deps)
GET /health/liveness     — alias for /health
GET /health/readiness    — DB + Redis check (fast, <1s), returns 200/503
GET /health/detailed     — full dependency health + queue depths
GET /debug/pipeline-trace — sequential end-to-end link check (admin/gated)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from sqlalchemy import text

from app.celery_app import celery_app
from app.config import get_settings
from app.db import AsyncSessionLocal
from app.redis_client import redis_client
from app.services.capacity_guard import check_capacity_sync

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_START_TIME = time.monotonic()
_CHECK_TIMEOUT_SECONDS = 2.0
_CELERY_QUEUES = ("video", "image", "text", "admin", "default")
_INSTALLED_FLAG = "_shortdrama_monitoring_installed"

# Provider health probe URLs — used by /debug/pipeline-trace
_PROVIDER_HEALTH_URLS: dict[str, str | None] = {}

_REGISTRY = CollectorRegistry()
_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ("method", "handler", "status"),
    registry=_REGISTRY,
)
_REQUEST_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "handler"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=_REGISTRY,
)
_UPTIME = Gauge("process_uptime_seconds", "API process uptime in seconds.", registry=_REGISTRY)
_QUEUE_LENGTH = Gauge(
    "celery_queue_length",
    "Approximate pending Celery messages by queue.",
    ("queue",),
    registry=_REGISTRY,
)
_QUEUE_SCRAPE_ERROR = Gauge(
    "celery_queue_scrape_error",
    "Whether queue length scraping failed.",
    ("queue",),
    registry=_REGISTRY,
)
_RECONCILIATION = Counter(
    "task_reconciliation_total",
    "Task reconciliation actions by outcome.",
    ("action",),  # "dispatched", "abandoned", "skipped", "errors"
    registry=_REGISTRY,
)
_ORPHAN_QUEUE = Gauge(
    "task_orphan_queued_count",
    "How many tasks are queued without a broker receipt (likely orphans).",
    registry=_REGISTRY,
)


def install_monitoring(app: FastAPI) -> None:
    if getattr(app.state, _INSTALLED_FLAG, False):
        return
    setattr(app.state, _INSTALLED_FLAG, True)

    @app.middleware("http")
    async def record_request_metrics(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            handler = _handler_label(request)
            if handler not in ("/metrics", "/_health"):
                _REQUESTS.labels(request.method, handler, str(status_code)).inc()
                _REQUEST_SECONDS.labels(request.method, handler).observe(time.perf_counter() - started)

    app.include_router(router)


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — validates the process is running, no deps needed."""
    return {"status": "ok"}


@router.get("/health/liveness")
async def health_liveness() -> dict[str, str]:
    """Alias for /health."""
    return {"status": "ok"}


@router.get("/health/readiness")
async def health_readiness() -> JSONResponse:
    """Readiness probe — checks DB + Redis (fast, <1s expected).

    Returns 200 if both are ok, 503 otherwise.
    Docker/K8s should use this endpoint instead of /health.
    """
    db, redis = await asyncio.gather(_check_db(), _check_redis())
    ok = db["status"] == "ok" and redis["status"] == "ok"
    return JSONResponse(
        content={
            "status": "ok" if ok else "degraded",
            "uptime_seconds": round(_uptime_seconds(), 1),
            "db": db,
            "redis": redis,
        },
        status_code=200 if ok else 503,
    )


@router.get("/health/detailed")
async def health_detailed() -> JSONResponse:
    """Full dependency health — DB, Redis, Celery workers, queue depths."""
    db, redis, celery = await asyncio.gather(_check_db(), _check_redis(), _check_celery())
    queue_lengths = await _redis_queue_lengths(_CELERY_QUEUES)
    total_pending = sum(queue_lengths.values())
    all_ok = all(item["status"] == "ok" for item in (db, redis, celery))
    body: dict[str, Any] = {
        "status": "ok" if all_ok else "degraded",
        "uptime_seconds": round(_uptime_seconds(), 1),
        "db": db,
        "redis": redis,
        "celery": celery,
        "queue_lengths": queue_lengths,
        "total_pending": total_pending,
    }
    logger.debug(
        "Detailed health -> status=%s celery=%s queues=%s",
        body["status"], celery.get("status"), total_pending,
    )
    return JSONResponse(body, status_code=200 if all_ok else 503)


@router.get("/debug/pipeline-trace")
async def pipeline_trace() -> JSONResponse:
    """Sequential end-to-end link detection.

    Runs each step in order and reports timing + status.
    This is **admin/gated** — not intended for production monitoring.
    """
    steps: list[dict[str, Any]] = []
    overall = "ok"

    # 1. DB
    db = await _check_db()
    steps.append({"name": "db", "status": db["status"], "detail": db.get("detail")})
    if db["status"] != "ok":
        overall = "degraded"

    # 2. Redis
    redis = await _check_redis()
    steps.append({"name": "redis", "status": redis["status"], "detail": redis.get("detail")})
    if redis["status"] != "ok":
        overall = "degraded"

    # 3. Celery broker receipt (set a key, read it back)
    broker_ok = False
    try:
        await asyncio.wait_for(redis_client.set("__probe_broker", "1", ex=10), timeout=1.0)
        val = await asyncio.wait_for(redis_client.get("__probe_broker"), timeout=1.0)
        broker_ok = val == "1"
    except Exception as exc:
        steps.append({"name": "celery_broker", "status": "error", "detail": str(exc)})
        overall = "degraded"
    else:
        steps.append({"name": "celery_broker", "status": "ok" if broker_ok else "error", "detail": "" if broker_ok else "readback mismatch"})
        if not broker_ok:
            overall = "degraded"

    # 4. Celery workers (ping-based, lightweight)
    celery = await _check_celery()
    steps.append({
        "name": "celery_workers",
        "status": celery["status"],
        "workers": celery.get("workers", 0),
        "queues": celery.get("queues", {}),
        "detail": celery.get("detail"),
    })
    if celery["status"] != "ok":
        overall = "degraded"

    # 5. Queue coverage
    coverage = await _check_queue_coverage()
    if coverage["status"] != "ok":
        overall = "degraded"
    steps.append({"name": "queue_coverage", **coverage})

    # 6. Provider key pool snapshots
    settings = get_settings()
    provider_capacity: dict[str, dict] = {}
    for provider in ("seedance", "seedream", "doubao", "kling"):
        try:
            cap = check_capacity_sync(provider)
            provider_capacity[provider] = {
                "available_slots": cap.available_slots,
                "total_concurrency": cap.total_concurrency,
                "used_slots": cap.used_slots,
                "cooldown_keys": cap.cooldown_keys,
            }
        except Exception as exc:
            provider_capacity[provider] = {"error": str(exc)}
    steps.append({"name": "provider_key_pool", "status": "ok", "capacity": provider_capacity})

    # 7. Provider API reachability (HEAD / models or equivalent)
    provider_reachability: dict[str, str] = {}
    provider_urls = _build_provider_probe_urls(settings)
    for name, url in provider_urls.items():
        if not url:
            provider_reachability[name] = "not_configured"
            continue
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.head(url, headers={"Authorization": f"Bearer {settings.ark_api_key}" if "ark" in url else ""})
                provider_reachability[name] = "ok" if resp.status_code < 500 else f"error_{resp.status_code}"
        except httpx.TimeoutException:
            provider_reachability[name] = "timeout"
            overall = "degraded"
        except httpx.ConnectError:
            provider_reachability[name] = "unreachable"
            overall = "degraded"
        except Exception as exc:
            provider_reachability[name] = f"error_{type(exc).__name__}"
            overall = "degraded"
    steps.append({"name": "provider_api_reachability", "status": "ok" if all(v == "ok" or v == "not_configured" for v in provider_reachability.values()) else "degraded", "providers": provider_reachability})

    # Determine final overall status
    any_error = any(s["status"] == "error" for s in steps)
    any_degraded = any(s["status"] == "degraded" or s.get("status") == "degraded" for s in steps)
    final_status = "error" if any_error else ("degraded" if any_degraded else "ok")

    return JSONResponse(content={
        "trace_id": f"trace_{int(time.time())}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "overall": final_status,
        "steps": steps,
        "recommendation": _trace_recommendation(steps),
    })


@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    _UPTIME.set(_uptime_seconds())
    await _refresh_queue_metrics()
    await _refresh_orphan_reconciliation_metrics()
    return PlainTextResponse(generate_latest(_REGISTRY).decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


# ------------------------------------------------------------------
# Internal health check helpers
# ------------------------------------------------------------------

async def _check_db() -> dict[str, Any]:
    async def query() -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(query(), timeout=_CHECK_TIMEOUT_SECONDS)
        return {"status": "ok"}
    except TimeoutError:
        return {"status": "error", "detail": "database check timed out"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _check_redis() -> dict[str, Any]:
    try:
        pong = await asyncio.wait_for(redis_client.ping(), timeout=_CHECK_TIMEOUT_SECONDS)
        return {"status": "ok" if pong else "error"}
    except TimeoutError:
        return {"status": "error", "detail": "redis check timed out"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _check_celery() -> dict[str, Any]:
    """Check Celery worker liveness using lightweight .ping().

    Uses .ping() instead of .active() — .active() times out when workers
    are busy processing tasks (normal operation), producing false degraded
    signals. .ping() is a simple broker round-trip.
    """
    try:
        pings = await asyncio.wait_for(
            asyncio.to_thread(_ping_celery_workers),
            timeout=_CHECK_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("Celery health check timed out (ping)")
        return {"status": "error", "detail": "celery ping timed out"}
    except Exception as exc:
        logger.warning("Celery health check error: %s", exc)
        return {"status": "error", "detail": str(exc)}

    if not pings:
        logger.warning("Celery health check: no workers responded to ping")
        return {"status": "degraded", "workers": 0, "detail": "no workers responded to ping"}

    worker_count = len(pings)
    # Also check queue coverage
    queues = await _check_queue_coverage()
    return {
        "status": "ok" if queues["status"] == "ok" else "degraded",
        "workers": worker_count,
        "queues": queues,
    }


def _ping_celery_workers() -> list[dict[str, Any]]:
    """Lightweight worker liveness — returns list of ping responses."""
    result = celery_app.control.inspect(timeout=1.5).ping()
    if not result:
        return []
    # result is dict like {'worker-video@h1': {'ok': 'pong'}}
    return [{"name": k, "ok": v} for k, v in result.items()]


async def _check_queue_coverage() -> dict[str, Any]:
    """Verify each expected queue has at least one active consumer.

    Uses .active_queues() which returns the queues each worker consumes.
    """
    try:
        queues = await asyncio.wait_for(
            asyncio.to_thread(_get_queue_consumers),
            timeout=_CHECK_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        return {"status": "error", "detail": "queue inspection timed out"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}

    # Build set of all queues currently being consumed
    consumed: set[str] = set()
    for worker_name, queue_list in queues.items():
        for q in queue_list:
            name = q.get("name") if isinstance(q, dict) else str(q)
            consumed.add(name)

    missing = [q for q in _CELERY_QUEUES if q not in consumed]
    if missing:
        logger.warning("Queue coverage: missing consumers for %s", missing)
        return {"status": "degraded", "missing_queues": missing, "active_queues": sorted(consumed)}
    return {"status": "ok", "active_queues": sorted(consumed)}


def _get_queue_consumers() -> dict[str, list[dict]]:
    """Return mapping of worker -> list of queues they consume."""
    result = celery_app.control.inspect(timeout=1.5).active_queues()
    return result if isinstance(result, dict) else {}


def _build_provider_probe_urls(settings) -> dict[str, str | None]:
    base = settings.ark_base_url.rstrip("/")
    return {
        "seedance": f"{base}/models",
        "seedream": f"{base}/models",
        "doubao": f"{base}/models",
        "ltx2.3": f"{settings.ltx_api_base_url.rstrip('/')}/health" if settings.ltx_api_base_url else None,
        "wan2.1": f"{settings.inference_api_base_url.rstrip('/')}/v1/health" if settings.inference_api_base_url else None,
    }


def _trace_recommendation(steps: list[dict[str, Any]]) -> str:
    failed = [s["name"] for s in steps if s.get("status") in ("error", "degraded")]
    if not failed:
        return "All checks passed."
    if "celery_broker" in failed:
        return "Celery broker (Redis) is unreachable — check Redis connection and CELERY_BROKER_URL."
    if "celery_workers" in failed:
        return "No Celery workers responded to ping — check worker containers are running and connected to the same broker."
    if "queue_coverage" in failed:
        return "Some Celery queues have no consumers — verify worker startup commands match expected queues."
    critical = ["db", "redis"]
    c = [f for f in failed if f in critical]
    if c:
        return f"Core dependency {' and '.join(c)} {'is' if len(c)==1 else 'are'} unavailable — check Docker container status."
    return f"Degraded links: {', '.join(failed)} — investigate each component."


async def _refresh_queue_metrics() -> None:
    try:
        lengths = await asyncio.wait_for(_redis_queue_lengths(_CELERY_QUEUES), timeout=_CHECK_TIMEOUT_SECONDS)
    except Exception:
        for queue in _CELERY_QUEUES:
            _QUEUE_SCRAPE_ERROR.labels(queue).set(1)
        return

    for queue, length in lengths.items():
        _QUEUE_LENGTH.labels(queue).set(length)
        _QUEUE_SCRAPE_ERROR.labels(queue).set(0)


async def _refresh_orphan_reconciliation_metrics() -> None:
    """Scrape count of tasks that are queued but likely orphaned (>3 min)."""
    try:
        async with AsyncSessionLocal() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM tasks
                    WHERE status = 'queued'
                      AND created_at < NOW() - make_interval(secs => 180)
                      AND (reconcile_attempts IS NULL OR reconcile_attempts < 3)
                    """
                ),
            )).scalar()
            _ORPHAN_QUEUE.set(row or 0)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Orphan metric scrape failed: %s", exc)


async def _redis_queue_lengths(queues: Iterable[str]) -> dict[str, int]:
    pipe = redis_client.pipeline(transaction=False)
    keys_by_queue = {queue: _celery_queue_keys(queue) for queue in queues}
    for keys in keys_by_queue.values():
        for key in keys:
            pipe.llen(key)

    raw_lengths = [int(value) for value in await pipe.execute()]
    offset = 0
    result: dict[str, int] = {}
    for queue, keys in keys_by_queue.items():
        result[queue] = sum(raw_lengths[offset:offset + len(keys)])
        offset += len(keys)
    return result


def _celery_queue_keys(queue: str) -> list[str]:
    return [queue, *(f"{queue}\x06\x16{priority}" for priority in range(10))]


def _handler_label(request: Request) -> str:
    route = request.scope.get("route")
    return str(getattr(route, "path", None) or "__unmatched__")


def _uptime_seconds() -> float:
    return time.monotonic() - _START_TIME
