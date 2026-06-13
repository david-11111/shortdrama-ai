"""
P8-QA-2: 核心链路冒烟测试 — 脚本 → 参考图 → 视频完整链路。

覆盖 P8 冒烟清单：
1. POST /api/director/script → task queued
2. POST /api/director/reference-images → task queued
3. POST /api/director/produce → task queued
4. POST /api/batch/generate-images → task queued + credits reserved
5. POST /api/batch/generate-videos → task queued + credits reserved
6. 任务取消 → 积分退款（通过 POST /api/tasks/{task_id}/cancel）
7. 并发限制 → 超限返回 429
8. 限流中间件 → 超限返回 429
9. rate_limit_config 对 video_gen 生效
10. rate_limit_config 对 image_gen 生效
"""
import pytest
from unittest.mock import patch


pytestmark = [pytest.mark.smoke, pytest.mark.asyncio]


# ─── 1. /api/director/script → task queued ──────────────────────────────────────

async def test_director_script_queued(client, test_user_pro):
    with patch("app.routes.director.celery_app.send_task"):
        resp = await client.post(
            "/api/director/script",
            json={"project_id": "proj_test_001", "query": "一个关于友情的短剧"},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert "task_id" in data


# ─── 2. /api/director/reference-images → task queued ────────────────────────────

async def test_director_reference_images_queued(client, test_user_pro):
    with patch("app.routes.director.celery_app.send_task"):
        resp = await client.post(
            "/api/director/reference-images",
            json={"project_id": "proj_test_001", "shot_indices": [0, 1, 2]},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert "task_id" in data


# ─── 3. /api/director/produce → task queued ─────────────────────────────────────

async def test_director_produce_queued(client, test_user_pro):
    with patch("app.routes.director.celery_app.send_task"):
        resp = await client.post(
            "/api/director/produce",
            json={"project_id": "proj_test_001"},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert "task_id" in data


# ─── 4. /api/batch/generate-images → queued + credits reserved ──────────────────

async def test_batch_generate_images_queued(client, test_user_pro, rate_limit_config):
    with patch("app.main.celery_app.send_task") as mock_send:
        resp = await client.post(
            "/api/batch/generate-images",
            json={"items": [{"prompt": "a cat"}, {"prompt": "a dog"}]},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "queued"
    assert len(data["child_task_ids"]) == 2
    assert data["total_credits_reserved"] > 0
    assert mock_send.call_count == 2


# ─── 5. /api/batch/generate-videos → queued + credits reserved ──────────────────

async def test_batch_generate_videos_queued(client, test_user_pro, rate_limit_config):
    with patch("app.main.celery_app.send_task") as mock_send:
        resp = await client.post(
            "/api/batch/generate-videos",
            json={"items": [{"prompt": "a sunset scene", "duration": 5}]},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "queued"
    assert len(data["child_task_ids"]) == 1
    assert data["total_credits_reserved"] > 0
    assert mock_send.call_count == 1


# ─── 6. 任务取消 → 积分退款（QA-008 已知 bug，此处验证当前行为） ──────────────────

async def test_task_cancel_accepted(client, test_user_pro, db_session, rate_limit_config):
    """验证取消接口可达（积分退款 bug QA-008 修复后此测试需升级为验证余额恢复）。"""
    from sqlalchemy import text

    with patch("app.main.celery_app.send_task"):
        resp = await client.post(
            "/api/batch/generate-images",
            json={"items": [{"prompt": "test cancel"}]},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 202
    task_id = resp.json()["child_task_ids"][0]

    cancel_resp = await client.post(
        f"/api/tasks/{task_id}/cancel",
        headers={"Authorization": test_user_pro["auth_header"]},
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"


# ─── 7. 并发限制 → 超限返回 429 ──────────────────────────────────────────────────

async def test_concurrent_limit_returns_429(client, test_user_free, db_session, rate_limit_config):
    from sqlalchemy import text

    for i in range(3):
        await db_session.execute(
            text("""
                INSERT INTO tasks (task_id, user_id, task_type, status, priority)
                VALUES (:tid, :uid, 'video_gen', 'running', 5)
            """),
            {"tid": f"fake_running_{i}", "uid": test_user_free["id"]},
        )

    with patch("app.main.celery_app.send_task"):
        resp = await client.post(
            "/api/batch/generate-videos",
            json={"items": [{"prompt": "test"}]},
            headers={"Authorization": test_user_free["auth_header"]},
        )
    assert resp.status_code == 429
    assert "Concurrent task limit exceeded" in resp.json()["detail"]["error"]


# ─── 8. 限流中间件 → 超限返回 429 ────────────────────────────────────────────────

async def test_rate_limit_video_gen_returns_429(client, test_user_free, rate_limit_config):
    """free tier video_gen 限额 5 次/小时，第 6 次应返回 429。"""
    import time
    from app.redis_client import redis_client

    user_id = test_user_free["id"]
    redis_key = f"rate_limit:{user_id}:video_gen"

    now = time.time()
    await redis_client.delete(redis_key)
    for i in range(5):
        await redis_client.zadd(redis_key, {f"{now + i}": now + i})
    await redis_client.expire(redis_key, 3610)

    with patch("app.main.celery_app.send_task"):
        resp = await client.post(
            "/api/batch/generate-videos",
            json={"items": [{"prompt": "test rate limit"}]},
            headers={"Authorization": test_user_free["auth_header"]},
        )

    await redis_client.delete(redis_key)
    assert resp.status_code == 429
    assert "Rate limit exceeded" in resp.json()["detail"]["error"]


# ─── 9. rate_limit_config 对 video_gen 生效 ──────────────────────────────────────

async def test_rate_limit_config_video_gen_applied(client, test_user_pro, rate_limit_config):
    """pro tier video_gen 限额 30 次/小时，首次请求应通过。"""
    with patch("app.main.celery_app.send_task"):
        resp = await client.post(
            "/api/batch/generate-videos",
            json={"items": [{"prompt": "test config"}]},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 202


# ─── 10. rate_limit_config 对 image_gen 生效 ─────────────────────────────────────

async def test_rate_limit_config_image_gen_applied(client, test_user_enterprise, rate_limit_config):
    """enterprise tier image_gen 限额 500 次/小时，首次请求应通过。"""
    with patch("app.main.celery_app.send_task"):
        resp = await client.post(
            "/api/batch/generate-images",
            json={"items": [{"prompt": "test enterprise"}]},
            headers={"Authorization": test_user_enterprise["auth_header"]},
        )
    assert resp.status_code == 202
