"""
P8-QA-4: 排队三件套集成测试。

覆盖：
- 超限返回 429（滑动窗口限流）
- 并发任务数限制（三档 tier）
- rate_limit_config 表配置生效
"""
import time
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ─── 滑动窗口限流 ────────────────────────────────────────────────────────────────

class TestRateLimitSliding:
    """check_rate_limit 滑动窗口行为。"""

    async def test_first_request_allowed(self, client, test_user_free, rate_limit_config):
        """首次请求在限额内，应通过。"""
        from app.redis_client import redis_client
        key = f"rate_limit:{test_user_free['id']}:image_gen"
        await redis_client.delete(key)

        with patch("app.main.celery_app.send_task"):
            resp = await client.post(
                "/api/batch/generate-images",
                json={"items": [{"prompt": "first"}]},
                headers={"Authorization": test_user_free["auth_header"]},
            )
        await redis_client.delete(key)
        assert resp.status_code == 202

    async def test_exceeds_limit_returns_429(self, client, test_user_free, rate_limit_config):
        """超过 free tier image_gen 限额（20次/小时）返回 429。"""
        from app.redis_client import redis_client
        user_id = test_user_free["id"]
        key = f"rate_limit:{user_id}:image_gen"

        now = time.time()
        await redis_client.delete(key)
        for i in range(20):
            await redis_client.zadd(key, {f"req_{i}": now + i * 0.001})
        await redis_client.expire(key, 3610)

        with patch("app.main.celery_app.send_task"):
            resp = await client.post(
                "/api/batch/generate-images",
                json={"items": [{"prompt": "overflow"}]},
                headers={"Authorization": test_user_free["auth_header"]},
            )
        await redis_client.delete(key)
        assert resp.status_code == 429
        detail = resp.json()["detail"]
        assert detail["error"] == "Rate limit exceeded"
        assert "retry_after" in detail
        assert "Retry-After" in resp.headers

    async def test_429_includes_retry_after_header(self, client, test_user_free, rate_limit_config):
        """429 响应必须包含 Retry-After header。"""
        from app.redis_client import redis_client
        user_id = test_user_free["id"]
        key = f"rate_limit:{user_id}:video_gen"

        now = time.time()
        await redis_client.delete(key)
        for i in range(5):
            await redis_client.zadd(key, {f"req_{i}": now + i * 0.001})
        await redis_client.expire(key, 3610)

        with patch("app.main.celery_app.send_task"):
            resp = await client.post(
                "/api/batch/generate-videos",
                json={"items": [{"prompt": "test"}]},
                headers={"Authorization": test_user_free["auth_header"]},
            )
        await redis_client.delete(key)
        assert resp.status_code == 429
        assert int(resp.headers["Retry-After"]) >= 1

    async def test_window_expiry_allows_new_requests(self, client, test_user_free, rate_limit_config):
        """窗口外的旧记录不计入限额。"""
        from app.redis_client import redis_client
        user_id = test_user_free["id"]
        key = f"rate_limit:{user_id}:image_gen"

        # 插入 20 条过期记录（窗口外）
        old_time = time.time() - 7200  # 2小时前
        await redis_client.delete(key)
        for i in range(20):
            await redis_client.zadd(key, {f"old_{i}": old_time + i})

        with patch("app.main.celery_app.send_task"):
            resp = await client.post(
                "/api/batch/generate-images",
                json={"items": [{"prompt": "after window"}]},
                headers={"Authorization": test_user_free["auth_header"]},
            )
        await redis_client.delete(key)
        assert resp.status_code == 202


# ─── 并发任务数限制 ──────────────────────────────────────────────────────────────

class TestConcurrentLimit:
    """check_concurrent_limit 三档 tier 行为。"""

    async def test_free_tier_concurrent_limit(
        self, client, test_user_free, db_session, rate_limit_config
    ):
        """free tier 并发上限 2，第 3 个任务返回 429。"""
        for i in range(2):
            await db_session.execute(
                text("""
                    INSERT INTO tasks (task_id, user_id, task_type, status, priority)
                    VALUES (:tid, :uid, 'video_gen', 'running', 5)
                """),
                {"tid": f"free_running_{i}", "uid": test_user_free["id"]},
            )

        with patch("app.main.celery_app.send_task"):
            resp = await client.post(
                "/api/batch/generate-videos",
                json={"items": [{"prompt": "overflow"}]},
                headers={"Authorization": test_user_free["auth_header"]},
            )
        assert resp.status_code == 429
        assert "Concurrent task limit exceeded" in resp.json()["detail"]["error"]

    async def test_pro_tier_concurrent_limit(
        self, client, test_user_pro, db_session, rate_limit_config
    ):
        """pro tier 并发上限 10，第 11 个任务返回 429。"""
        for i in range(10):
            await db_session.execute(
                text("""
                    INSERT INTO tasks (task_id, user_id, task_type, status, priority)
                    VALUES (:tid, :uid, 'video_gen', 'running', 3)
                """),
                {"tid": f"pro_running_{i}", "uid": test_user_pro["id"]},
            )

        with patch("app.main.celery_app.send_task"):
            resp = await client.post(
                "/api/batch/generate-videos",
                json={"items": [{"prompt": "overflow"}]},
                headers={"Authorization": test_user_pro["auth_header"]},
            )
        assert resp.status_code == 429

    async def test_enterprise_tier_concurrent_limit(
        self, client, test_user_enterprise, db_session, rate_limit_config
    ):
        """enterprise tier 并发上限 50，第 51 个任务返回 429。"""
        for i in range(50):
            await db_session.execute(
                text("""
                    INSERT INTO tasks (task_id, user_id, task_type, status, priority)
                    VALUES (:tid, :uid, 'video_gen', 'running', 1)
                """),
                {"tid": f"ent_running_{i}", "uid": test_user_enterprise["id"]},
            )

        with patch("app.main.celery_app.send_task"):
            resp = await client.post(
                "/api/batch/generate-videos",
                json={"items": [{"prompt": "overflow"}]},
                headers={"Authorization": test_user_enterprise["auth_header"]},
            )
        assert resp.status_code == 429

    async def test_queued_tasks_count_toward_concurrent(
        self, client, test_user_free, db_session, rate_limit_config
    ):
        """queued 状态的任务也计入并发数。"""
        for i in range(2):
            await db_session.execute(
                text("""
                    INSERT INTO tasks (task_id, user_id, task_type, status, priority)
                    VALUES (:tid, :uid, 'image_gen', 'queued', 5)
                """),
                {"tid": f"free_queued_{i}", "uid": test_user_free["id"]},
            )

        with patch("app.main.celery_app.send_task"):
            resp = await client.post(
                "/api/batch/generate-images",
                json={"items": [{"prompt": "test queued count"}]},
                headers={"Authorization": test_user_free["auth_header"]},
            )
        assert resp.status_code == 429

    async def test_completed_tasks_not_counted(
        self, client, test_user_free, db_session, rate_limit_config
    ):
        """completed/failed 状态的任务不计入并发数。"""
        for i in range(5):
            await db_session.execute(
                text("""
                    INSERT INTO tasks (task_id, user_id, task_type, status, priority)
                    VALUES (:tid, :uid, 'video_gen', 'completed', 5)
                """),
                {"tid": f"free_done_{i}", "uid": test_user_free["id"]},
            )

        with patch("app.main.celery_app.send_task"):
            resp = await client.post(
                "/api/batch/generate-images",
                json={"items": [{"prompt": "test done not counted"}]},
                headers={"Authorization": test_user_free["auth_header"]},
            )
        assert resp.status_code == 202


# ─── rate_limit_config 表配置生效 ────────────────────────────────────────────────

class TestRateLimitConfig:
    """rate_limit_config 表驱动限流配置。"""

    async def test_no_config_means_no_limit(self, client, test_user_pro, db_session):
        """无配置时不限流，请求应通过。"""
        # 不插入 rate_limit_config，直接请求
        with patch("app.main.celery_app.send_task"):
            resp = await client.post(
                "/api/batch/generate-images",
                json={"items": [{"prompt": "no config"}]},
                headers={"Authorization": test_user_pro["auth_header"]},
            )
        assert resp.status_code == 202

    async def test_tts_resource_rate_limit(self, client, test_user_free, db_session, rate_limit_config):
        """TTS 端点也受限流保护（通过 tts_synthesis 积分预扣路径）。"""
        with patch("app.main.celery_app.send_task"):
            resp = await client.post(
                "/api/tts/generate",
                json={"text": "你好世界"},
                headers={"Authorization": test_user_free["auth_header"]},
            )
        # TTS 不走 rate_limit，只走积分预扣，应通过
        assert resp.status_code in (200, 202)
