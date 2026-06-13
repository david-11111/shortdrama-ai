"""
QA-004 复现用例：str(item) 写入 tasks.payload，应为 json.dumps。

预期：tasks.payload 字段存储合法 JSON 字符串。
实际：存储 Python repr 字符串（如 "{'prompt': 'test'}"），无法被 json.loads 解析。
"""
import json
import pytest
from unittest.mock import patch
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_batch_video_payload_is_invalid_json(client, test_user_pro, db_session, rate_limit_config):
    """复现：批量视频任务的 payload 字段不是合法 JSON。"""
    item = {"prompt": "test payload", "duration": 5}

    with patch("app.main.celery_app.send_task"):
        resp = await client.post(
            "/api/batch/generate-videos",
            json={"items": [item]},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 202
    task_id = resp.json()["child_task_ids"][0]

    result = await db_session.execute(
        text("SELECT payload FROM tasks WHERE task_id = :tid"),
        {"tid": task_id},
    )
    payload_str = result.scalar()

    # BUG：str(item) 产生 Python repr，json.loads 会抛 JSONDecodeError
    try:
        json.loads(payload_str)
        # 修复后应能到达这里
    except json.JSONDecodeError:
        pytest.fail(
            f"BUG QA-004 confirmed: payload is not valid JSON: {payload_str!r}"
        )


async def test_batch_image_payload_is_invalid_json(client, test_user_pro, db_session, rate_limit_config):
    """复现：批量图片任务的 payload 字段不是合法 JSON。"""
    item = {"prompt": "test image payload"}

    with patch("app.main.celery_app.send_task"):
        resp = await client.post(
            "/api/batch/generate-images",
            json={"items": [item]},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 202
    task_id = resp.json()["child_task_ids"][0]

    result = await db_session.execute(
        text("SELECT payload FROM tasks WHERE task_id = :tid"),
        {"tid": task_id},
    )
    payload_str = result.scalar()

    try:
        json.loads(payload_str)
    except json.JSONDecodeError:
        pytest.fail(
            f"BUG QA-004 confirmed: payload is not valid JSON: {payload_str!r}"
        )
