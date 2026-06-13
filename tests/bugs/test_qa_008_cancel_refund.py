"""
QA-008 复现用例：取消任务不退预扣积分（tasks.py:124 TODO 未实现）。

预期：取消 queued 任务后，credits_reserved 退还到 credit_accounts.balance。
实际：tasks.py:124 有 TODO 注释，退款逻辑未实现，积分永久丢失。
"""
import pytest
from unittest.mock import patch
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_cancel_task_does_not_refund_credits(client, test_user_pro, db_session, rate_limit_config):
    """复现：取消任务后积分未退还。"""
    # 提交一个任务
    with patch("app.main.celery_app.send_task"):
        resp = await client.post(
            "/api/batch/generate-images",
            json={"items": [{"prompt": "cancel test"}]},
            headers={"Authorization": test_user_pro["auth_header"]},
        )
    assert resp.status_code == 202
    task_id = resp.json()["child_task_ids"][0]

    # 查询预扣后余额
    result = await db_session.execute(
        text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
        {"uid": test_user_pro["id"]},
    )
    balance_after_reserve = result.scalar()

    # 取消任务
    cancel_resp = await client.post(
        f"/api/tasks/{task_id}/cancel",
        headers={"Authorization": test_user_pro["auth_header"]},
    )
    assert cancel_resp.status_code == 200

    # 查询取消后余额
    result = await db_session.execute(
        text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
        {"uid": test_user_pro["id"]},
    )
    balance_after_cancel = result.scalar()

    # BUG：积分未退还，balance_after_cancel == balance_after_reserve
    assert balance_after_cancel > balance_after_reserve, (
        f"BUG QA-008 confirmed: credits not refunded after cancel. "
        f"balance_after_reserve={balance_after_reserve}, "
        f"balance_after_cancel={balance_after_cancel}"
    )
