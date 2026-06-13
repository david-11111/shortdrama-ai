"""
QA-005 复现用例：批量端点积分预扣中途失败，前面已扣不回滚。

预期：任一子任务预扣失败时，前面已扣的积分全部退还。
实际：前面已扣的积分丢失（财务漏洞）。
"""
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_partial_reserve_failure_leaks_credits(client, test_user_pro, db_session, rate_limit_config):
    """
    复现：3 个子任务，第 2 个预扣失败，第 1 个已扣的积分未退还。
    """
    # 查询初始余额
    result = await db_session.execute(
        text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
        {"uid": test_user_pro["id"]},
    )
    balance_before = result.scalar()

    call_count = 0

    async def mock_reserve(user_id, operation, quantity=1):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            from app.services.credits import InsufficientCreditsError
            raise InsufficientCreditsError("Simulated failure on 2nd reserve")
        from app.services.credits import credit_service
        return await credit_service._reserve(user_id, operation, quantity)

    with patch("app.main.reserve_credits", side_effect=mock_reserve):
        resp = await client.post(
            "/api/batch/generate-images",
            json={"items": [{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}]},
            headers={"Authorization": test_user_pro["auth_header"]},
        )

    # 请求应失败（积分不足）
    assert resp.status_code in (402, 400, 500)

    # 查询失败后余额
    result = await db_session.execute(
        text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
        {"uid": test_user_pro["id"]},
    )
    balance_after = result.scalar()

    # BUG：第 1 个已扣的积分未退还，balance_after < balance_before
    assert balance_after == balance_before, (
        f"BUG QA-005 confirmed: credits leaked. "
        f"before={balance_before}, after={balance_after}, "
        f"leaked={balance_before - balance_after}"
    )
