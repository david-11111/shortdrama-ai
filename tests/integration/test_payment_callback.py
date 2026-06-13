"""
P8-QA-6: 支付回调验签测试。

覆盖：
- 微信回调：签名错误拒绝处理
- 微信回调：正确格式通过
- 微信回调：重复回调幂等
- 支付宝回调：签名错误拒绝处理
- 支付宝回调：正确格式通过
- 支付宝回调：非 TRADE_SUCCESS 状态拒绝
- 未配置支付方式时拒绝处理

注意：payment_service 内部用 AsyncSessionLocal，pending_order 必须提交数据。
      get_settings 有 lru_cache，直接 patch payment_service 实例的 verify_* 方法。
"""
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.services.auth import hash_password

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def pending_order():
    """创建 pending 订单并提交（payment_service 用独立连接，必须提交）。"""
    username = f"pay_test_{uuid.uuid4().hex[:6]}"
    order_no = f"ORD_TEST_{uuid.uuid4().hex[:8].upper()}"

    async with AsyncSessionLocal() as s:
        async with s.begin():
            result = await s.execute(
                text("""
                    INSERT INTO users (username, email, password_hash, tier, status)
                    VALUES (:u, :e, :p, 'free', 'active')
                    RETURNING id
                """),
                {"u": username, "e": f"{username}@qa.test", "p": hash_password("x")},
            )
            user_id = result.scalar()
            await s.execute(
                text("INSERT INTO credit_accounts (user_id, balance) VALUES (:uid, 0)"),
                {"uid": user_id},
            )
            await s.execute(
                text("""
                    INSERT INTO orders (order_no, user_id, amount_cents, credits, payment_method, status)
                    VALUES (:order_no, :user_id, 990, 100, 'wechat', 'pending')
                """),
                {"order_no": order_no, "user_id": user_id},
            )

    yield {"order_no": order_no, "user_id": user_id}

    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(text("DELETE FROM credit_transactions WHERE user_id = :uid"), {"uid": user_id})
            await s.execute(text("DELETE FROM orders WHERE order_no = :o"), {"o": order_no})
            await s.execute(text("DELETE FROM credit_accounts WHERE user_id = :uid"), {"uid": user_id})
            await s.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})


# ─── 微信回调 ────────────────────────────────────────────────────────────────────

class TestWechatCallback:

    async def test_verify_returns_none_rejects(self, client):
        """verify_wechat_callback 返回 None 时，路由返回 400。"""
        with patch(
            "app.services.payment.payment_service.verify_wechat_callback",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.post(
                "/api/payment/callback/wechat",
                content=b'{"event_type": "TRANSACTION.SUCCESS"}',
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 400

    async def test_valid_callback_processes_payment(self, client, pending_order):
        """verify 通过后，process_payment_success 执行，返回 SUCCESS。"""
        with patch(
            "app.services.payment.payment_service.verify_wechat_callback",
            new=AsyncMock(return_value={
                "order_no": pending_order["order_no"],
                "trade_no": "wx_trade_valid_001",
            }),
        ):
            resp = await client.post(
                "/api/payment/callback/wechat",
                content=b'{}',
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 200
        assert resp.json()["code"] == "SUCCESS"

    async def test_duplicate_callback_idempotent(self, client, pending_order):
        """重复回调幂等，第二次也返回 200。"""
        mock_result = {
            "order_no": pending_order["order_no"],
            "trade_no": "wx_trade_dup_001",
        }
        with patch(
            "app.services.payment.payment_service.verify_wechat_callback",
            new=AsyncMock(return_value=mock_result),
        ):
            resp1 = await client.post(
                "/api/payment/callback/wechat",
                content=b'{}',
                headers={"Content-Type": "application/json"},
            )
            resp2 = await client.post(
                "/api/payment/callback/wechat",
                content=b'{}',
                headers={"Content-Type": "application/json"},
            )
        assert resp1.status_code == 200
        assert resp2.status_code == 200

    async def test_unknown_order_raises(self, client):
        """verify 通过但订单不存在时，process_payment_success 抛异常，返回 500。"""
        with patch(
            "app.services.payment.payment_service.verify_wechat_callback",
            new=AsyncMock(return_value={
                "order_no": "ORD_NONEXISTENT_999",
                "trade_no": "wx_trade_002",
            }),
        ):
            resp = await client.post(
                "/api/payment/callback/wechat",
                content=b'{}',
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code in (400, 500)

    async def test_wechat_verify_rejects_missing_api_key(self):
        """wechat_api_key 未配置时，verify_wechat_callback 返回 None。"""
        from app.services.payment import PaymentService
        from unittest.mock import MagicMock
        svc = PaymentService()
        with patch("app.services.payment.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(wechat_api_key="")
            result = await svc.verify_wechat_callback({}, b'{}')
        assert result is None

    async def test_wechat_verify_rejects_wrong_event_type(self):
        """非 TRANSACTION.SUCCESS 事件类型，verify 返回 None。"""
        from app.services.payment import PaymentService
        from unittest.mock import MagicMock
        svc = PaymentService()
        body = json.dumps({"event_type": "REFUND.SUCCESS", "resource": {}}).encode()
        with patch("app.services.payment.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(wechat_api_key="test_key")
            result = await svc.verify_wechat_callback({}, body)
        assert result is None


# ─── 支付宝回调 ──────────────────────────────────────────────────────────────────

class TestAlipayCallback:

    async def test_verify_returns_none_rejects(self, client):
        """verify_alipay_callback 返回 None 时，路由返回 fail（400）。"""
        with patch(
            "app.services.payment.payment_service.verify_alipay_callback",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.post(
                "/api/payment/callback/alipay",
                data={"trade_status": "TRADE_CLOSED"},
            )
        assert resp.status_code == 400

    async def test_valid_alipay_callback_processes(self, client, pending_order):
        """verify 通过后，process_payment_success 执行，返回 success。"""
        with patch(
            "app.services.payment.payment_service.verify_alipay_callback",
            new=AsyncMock(return_value={
                "order_no": pending_order["order_no"],
                "trade_no": "ali_trade_valid_001",
            }),
        ):
            resp = await client.post(
                "/api/payment/callback/alipay",
                data={"trade_status": "TRADE_SUCCESS"},
            )
        assert resp.status_code == 200
        assert resp.text == "success"

    async def test_alipay_verify_rejects_missing_app_id(self):
        """alipay_app_id 未配置时，verify_alipay_callback 返回 None。"""
        from app.services.payment import PaymentService
        from unittest.mock import MagicMock
        svc = PaymentService()
        with patch("app.services.payment.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(alipay_app_id="")
            result = await svc.verify_alipay_callback({"trade_status": "TRADE_SUCCESS"})
        assert result is None

    async def test_alipay_verify_rejects_non_trade_success(self):
        """非 TRADE_SUCCESS 状态，verify 返回 None。"""
        from app.services.payment import PaymentService
        from unittest.mock import MagicMock
        svc = PaymentService()
        with patch("app.services.payment.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(alipay_app_id="test_app")
            result = await svc.verify_alipay_callback({
                "trade_status": "TRADE_CLOSED",
                "out_trade_no": "ORD_X",
                "trade_no": "ali_X",
            })
        assert result is None

    async def test_alipay_verify_rejects_missing_trade_no(self):
        """缺少 trade_no 字段，verify 返回 None。"""
        from app.services.payment import PaymentService
        from unittest.mock import MagicMock
        svc = PaymentService()
        with patch("app.services.payment.get_settings") as mock_cfg:
            mock_cfg.return_value = MagicMock(alipay_app_id="test_app")
            result = await svc.verify_alipay_callback({
                "trade_status": "TRADE_SUCCESS",
                "out_trade_no": "ORD_X",
                # 缺少 trade_no
            })
        assert result is None
