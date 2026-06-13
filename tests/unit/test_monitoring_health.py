from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from monitoring import health


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_monitoring_routes_expose_health_and_metrics(monkeypatch):
    async def queue_lengths(queues):
        return {queue: 0 for queue in queues}

    monkeypatch.setattr(health, "_redis_queue_lengths", queue_lengths)

    app = FastAPI()
    health.install_monitoring(app)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/health")).json() == {"status": "ok"}
        await client.get("/missing/path")
        metrics = (await client.get("/metrics")).text

    assert 'http_requests_total{handler="__unmatched__",method="GET",status="404"}' in metrics
    assert "http_request_duration_seconds_bucket" in metrics
    assert 'celery_queue_scrape_error{queue="video"} 0.0' in metrics


@pytest.mark.asyncio
async def test_metrics_reports_queue_scrape_failure_without_fake_length(monkeypatch):
    async def fail_queue_lengths(_queues):
        raise TimeoutError("redis unavailable")

    monkeypatch.setattr(health, "_redis_queue_lengths", fail_queue_lengths)
    app = FastAPI()
    health.install_monitoring(app)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        metrics = (await client.get("/metrics")).text

    assert 'celery_queue_scrape_error{queue="video"} 1.0' in metrics


@pytest.mark.asyncio
async def test_detailed_health_returns_503_when_dependency_is_degraded(monkeypatch):
    monkeypatch.setattr(health, "_check_db", lambda: _status("ok"))
    monkeypatch.setattr(health, "_check_redis", lambda: _status("ok"))
    monkeypatch.setattr(health, "_check_celery", lambda: _status("degraded"))
    app = FastAPI()
    health.install_monitoring(app)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/detailed")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


async def _status(value: str) -> dict[str, str]:
    return {"status": value}
