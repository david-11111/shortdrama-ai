"""
QA-001 复现用例：_dispatch_director_task 硬编码派发到 generate_text_task。

预期：director/script 应派发到 director_script_task，
      director/reference-images 应派发到 director_ref_images_task，
      director/produce 应派发到 director_produce_task。
实际：全部派发到 text_tasks.generate_text_task。
"""
import pytest
from unittest.mock import patch, call

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_director_script_dispatches_wrong_task(client, test_user_pro):
    """复现：/director/script 派发到错误的 Celery 任务名。"""
    with patch("app.routes.director.celery_app.send_task") as mock_send:
        resp = await client.post(
            "/director/script",
            json={"project_id": "proj_001", "query": "test"},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 200

    # BUG：实际调用的是 generate_text_task，不是 director_script_task
    actual_task_name = mock_send.call_args[0][0]
    assert actual_task_name == "app.tasks.text_tasks.generate_text_task", (
        f"BUG QA-001 confirmed: task name is '{actual_task_name}'"
    )
    # 修复后此断言应改为：
    # assert actual_task_name == "app.tasks.director_tasks.director_script_task"


async def test_director_reference_images_dispatches_wrong_task(client, test_user_pro):
    """复现：/director/reference-images 派发到错误的 Celery 任务名。"""
    with patch("app.routes.director.celery_app.send_task") as mock_send:
        resp = await client.post(
            "/director/reference-images",
            json={"project_id": "proj_001"},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 200
    actual_task_name = mock_send.call_args[0][0]
    assert actual_task_name == "app.tasks.text_tasks.generate_text_task", (
        f"BUG QA-001 confirmed: task name is '{actual_task_name}'"
    )


async def test_director_produce_dispatches_wrong_task(client, test_user_pro):
    """复现：/director/produce 派发到错误的 Celery 任务名。"""
    with patch("app.routes.director.celery_app.send_task") as mock_send:
        resp = await client.post(
            "/director/produce",
            json={"project_id": "proj_001"},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 200
    actual_task_name = mock_send.call_args[0][0]
    assert actual_task_name == "app.tasks.text_tasks.generate_text_task", (
        f"BUG QA-001 confirmed: task name is '{actual_task_name}'"
    )
