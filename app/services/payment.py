"""Payment service: order creation + callback processing."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.security.signing import parse_wechat_v3_callback, verify_alipay_rsa2_signature

logger = logging.getLogger(__name__)


class PaymentService:
    CREDIT_PLANS = [
        {"id": "basic", "name": "基础包", "credits": 100, "price_cents": 990, "description": "100 积分"},
        {"id": "standard", "name": "标准包", "credits": 500, "price_cents": 3990, "description": "500 积分（8折）"},
        {"id": "premium", "name": "高级包", "credits": 2000, "price_cents": 12900, "description": "2000 积分（6.5折）"},
        {"id": "enterprise", "name": "企业包", "credits": 10000, "price_cents": 49900, "description": "10000 积分（5折）"},
    ]

    TIER_PLANS = [
        {
            "id": "pro_month",
            "name": "PRO 月卡",
            "target_tier": "pro",
            "tier_days": 30,
            "price_cents": 2900,
            "description": "并发和限流提升，适合日常创作",
        },
        {
            "id": "pro_quarter",
            "name": "PRO 季卡",
            "target_tier": "pro",
            "tier_days": 90,
            "price_cents": 7900,
            "description": "季卡折扣，持续创作更省",
        },
        {
            "id": "enterprise_month",
            "name": "企业月卡",
            "target_tier": "enterprise",
            "tier_days": 30,
            "price_cents": 12900,
            "description": "最高优先级与更高配额",
        },
    ]

    # Backward compatibility for old /payment/plans response shape
    PRICING_PLANS = CREDIT_PLANS

    def get_plan(self, plan_id: str, order_type: str = "topup") -> dict[str, Any] | None:
        plans = self.CREDIT_PLANS if order_type == "topup" else self.TIER_PLANS
        for plan in plans:
            if plan["id"] == plan_id:
                return plan
        return None

    def generate_order_no(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"ORD{ts}{uuid.uuid4().hex[:8].upper()}"

    async def create_order(
        self,
        user_id: int,
        plan_id: str,
        payment_method: str,
        order_type: str = "topup",
    ) -> dict[str, Any]:
        if order_type not in ("topup", "tier_upgrade"):
            raise ValueError(f"Invalid order type: {order_type}")

        plan = self.get_plan(plan_id, order_type=order_type)
        if not plan:
            raise ValueError(f"Invalid plan: {plan_id}")

        order_no = self.generate_order_no()
        credits = int(plan.get("credits", 0)) if order_type == "topup" else 0
        tier_target = str(plan.get("target_tier", "") or "") if order_type == "tier_upgrade" else ""
        tier_days = int(plan.get("tier_days", 0) or 0) if order_type == "tier_upgrade" else 0

        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO orders (
                            order_no, user_id, amount_cents, credits, payment_method, status,
                            order_type, plan_id, tier_target, tier_days
                        )
                        VALUES (
                            :order_no, :user_id, :amount_cents, :credits, :payment_method, 'pending',
                            :order_type, :plan_id, :tier_target, :tier_days
                        )
                        """
                    ),
                    {
                        "order_no": order_no,
                        "user_id": user_id,
                        "amount_cents": int(plan["price_cents"]),
                        "credits": credits,
                        "payment_method": payment_method,
                        "order_type": order_type,
                        "plan_id": plan_id,
                        "tier_target": tier_target or None,
                        "tier_days": tier_days,
                    },
                )

        return {
            "order_no": order_no,
            "amount_cents": int(plan["price_cents"]),
            "credits": credits,
            "payment_method": payment_method,
            "order_type": order_type,
            "target_tier": tier_target,
            "tier_days": tier_days,
            "plan_id": plan_id,
        }

    async def create_wechat_native_order(self, order_no: str, amount_cents: int, description: str) -> dict[str, Any]:
        settings = get_settings()
        if not settings.wechat_mch_id:
            raise RuntimeError("WeChat Pay not configured")
        if not settings.wechat_private_key_path or not settings.wechat_cert_serial:
            raise RuntimeError("WeChat Pay signing is not configured")
        raise RuntimeError("WeChat Pay native order signing is not implemented")

    async def create_alipay_order(self, order_no: str, amount_cents: int, description: str) -> dict[str, Any]:
        settings = get_settings()
        if not settings.alipay_app_id:
            raise RuntimeError("Alipay not configured")

        amount_yuan = f"{amount_cents / 100:.2f}"
        params = {
            "app_id": settings.alipay_app_id,
            "method": "alipay.trade.page.pay",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "notify_url": settings.alipay_notify_url,
            "return_url": settings.alipay_return_url,
            "biz_content": json.dumps(
                {
                    "out_trade_no": order_no,
                    "total_amount": amount_yuan,
                    "subject": description,
                    "product_code": "FAST_INSTANT_TRADE_PAY",
                },
                ensure_ascii=False,
            ),
        }
        return {
            "payment_url": "https://openapi.alipay.com/gateway.do",
            "params": params,
            "order_no": order_no,
        }

    async def process_payment_success(self, order_no: str, trade_no: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    text("SELECT * FROM orders WHERE order_no = :order_no FOR UPDATE"),
                    {"order_no": order_no},
                )
                order = result.mappings().first()
                if not order:
                    raise ValueError(f"Order not found: {order_no}")
                if order["status"] == "paid":
                    return {"message": "Already processed", "order_no": order_no}
                if order["status"] not in ("processing", "pending"):
                    raise ValueError(f"Order {order_no} in unexpected status: {order['status']}")

                await session.execute(
                    text(
                        """
                        UPDATE orders
                        SET status = 'paid', trade_no = :trade_no, paid_at = NOW(), updated_at = NOW()
                        WHERE order_no = :order_no
                        """
                    ),
                    {"order_no": order_no, "trade_no": trade_no},
                )

                order_type = str(order.get("order_type") or "topup")
                if order_type == "tier_upgrade":
                    await self._apply_tier_upgrade(
                        session,
                        user_id=int(order["user_id"]),
                        target_tier=str(order.get("tier_target") or "pro"),
                        tier_days=int(order.get("tier_days") or 0),
                        order_no=order_no,
                    )
                    logger.info(
                        "Payment success tier upgrade: order=%s user=%s tier=%s days=%s",
                        order_no,
                        order["user_id"],
                        order.get("tier_target"),
                        order.get("tier_days"),
                    )
                    return {
                        "message": "Payment processed",
                        "order_no": order_no,
                        "order_type": "tier_upgrade",
                        "target_tier": order.get("tier_target"),
                        "tier_days": int(order.get("tier_days") or 0),
                    }

                balance_result = await session.execute(
                    text(
                        """
                        UPDATE credit_accounts
                        SET balance = balance + :credits, updated_at = NOW()
                        WHERE user_id = :user_id
                        RETURNING balance
                        """
                    ),
                    {"credits": int(order["credits"]), "user_id": int(order["user_id"])},
                )
                balance_after = balance_result.scalar_one_or_none()
                if balance_after is None:
                    create_result = await session.execute(
                        text(
                            """
                            INSERT INTO credit_accounts (user_id, balance)
                            VALUES (:user_id, :balance)
                            RETURNING balance
                            """
                        ),
                        {"user_id": int(order["user_id"]), "balance": int(order["credits"])},
                    )
                    balance_after = int(create_result.scalar_one())

                await session.execute(
                    text(
                        """
                        INSERT INTO credit_transactions (user_id, amount, balance_after, tx_type, description)
                        VALUES (:user_id, :amount, :balance_after, 'topup', :description)
                        """
                    ),
                    {
                        "user_id": int(order["user_id"]),
                        "amount": int(order["credits"]),
                        "balance_after": int(balance_after),
                        "description": f"Topup {int(order['credits'])} credits (order {order_no})",
                    },
                )

        logger.info("Payment success topup: order=%s credits=%s", order_no, order["credits"])
        return {
            "message": "Payment processed",
            "order_no": order_no,
            "order_type": "topup",
            "credits": int(order["credits"]),
        }

    async def _apply_tier_upgrade(
        self,
        session: Any,
        *,
        user_id: int,
        target_tier: str,
        tier_days: int,
        order_no: str,
    ) -> None:
        if target_tier not in ("pro", "enterprise"):
            raise ValueError(f"Unsupported tier target: {target_tier}")
        if tier_days <= 0:
            raise ValueError(f"Invalid tier duration: {tier_days}")

        user_result = await session.execute(
            text("SELECT tier, tier_expires_at FROM users WHERE id = :uid FOR UPDATE"),
            {"uid": user_id},
        )
        user_row = user_result.mappings().first()
        if not user_row:
            raise ValueError(f"User not found for tier upgrade: {user_id}")

        await session.execute(
            text(
                """
                UPDATE users
                SET tier = CAST(:target_tier AS VARCHAR(20)),
                    tier_expires_at = (
                        CASE
                            WHEN tier = CAST(:target_tier AS VARCHAR(20))
                             AND tier_expires_at IS NOT NULL
                             AND tier_expires_at > NOW()
                                THEN tier_expires_at + make_interval(days => :tier_days)
                            ELSE NOW() + make_interval(days => :tier_days)
                        END
                    ),
                    updated_at = NOW()
                WHERE id = :uid
                """
            ),
            {"uid": user_id, "target_tier": target_tier, "tier_days": tier_days},
        )

        balance_row = await session.execute(
            text("SELECT balance FROM credit_accounts WHERE user_id = :uid FOR UPDATE"),
            {"uid": user_id},
        )
        balance_after = balance_row.scalar_one_or_none()
        if balance_after is None:
            create_result = await session.execute(
                text(
                    """
                    INSERT INTO credit_accounts (user_id, balance)
                    VALUES (:uid, 0)
                    RETURNING balance
                    """
                ),
                {"uid": user_id},
            )
            balance_after = int(create_result.scalar_one())

        await session.execute(
            text(
                """
                INSERT INTO credit_transactions (user_id, amount, balance_after, tx_type, description)
                VALUES (:user_id, 0, :balance_after, 'bonus', :description)
                """
            ),
            {
                "user_id": user_id,
                "balance_after": int(balance_after),
                "description": f"Tier upgraded to {target_tier} for {tier_days} days (order {order_no})",
            },
        )

    async def verify_wechat_callback(self, headers: dict[str, str], body: bytes) -> dict[str, Any] | None:
        settings = get_settings()
        if not settings.wechat_api_key:
            logger.warning("WeChat callback received but wechat_api_key not configured")
            return None

        platform_cert_pem: str | None = None
        cert_path = settings.wechat_private_key_path.replace("apiclient_key.pem", "platform_cert.pem")
        if cert_path:
            try:
                with open(cert_path, encoding="utf-8") as f:
                    platform_cert_pem = f.read()
            except OSError:
                logger.warning("WeChat platform cert not found at %s, skip signature verification", cert_path)

        try:
            plaintext = parse_wechat_v3_callback(
                headers={k.lower(): v for k, v in headers.items()},
                body=body,
                api_v3_key=settings.wechat_api_key,
                platform_cert_pem=platform_cert_pem,
            )
        except Exception as exc:
            logger.error("WeChat callback parse failed: %s", exc)
            return None

        if not plaintext:
            return None

        order_no = plaintext.get("out_trade_no")
        trade_no = plaintext.get("transaction_id")
        if not order_no or not trade_no:
            logger.warning("WeChat callback missing order_no or trade_no")
            return None

        return await self._check_order_idempotent(order_no, trade_no, "wechat")

    async def verify_alipay_callback(self, params: dict[str, Any]) -> dict[str, Any] | None:
        settings = get_settings()
        if not settings.alipay_app_id:
            logger.warning("Alipay callback received but alipay_app_id not configured")
            return None

        if settings.alipay_public_key:
            pub_key_pem = settings.alipay_public_key
            if not pub_key_pem.startswith("-----"):
                pub_key_pem = "-----BEGIN PUBLIC KEY-----\n" + pub_key_pem + "\n-----END PUBLIC KEY-----"
            if not verify_alipay_rsa2_signature(params, pub_key_pem):
                logger.warning("Alipay RSA2 signature verification failed")
                return None

        if params.get("trade_status") != "TRADE_SUCCESS":
            return None

        order_no = params.get("out_trade_no")
        trade_no = params.get("trade_no")
        if not order_no or not trade_no:
            logger.warning("Alipay callback missing order_no or trade_no")
            return None

        return await self._check_order_idempotent(order_no, trade_no, "alipay")

    async def _check_order_idempotent(self, order_no: str, trade_no: str, channel: str) -> dict[str, Any] | None:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    text("SELECT status FROM orders WHERE order_no = :order_no FOR UPDATE"),
                    {"order_no": order_no},
                )
                row = result.mappings().first()
                if not row:
                    logger.warning("%s callback for unknown order: %s", channel, order_no)
                    return None
                if row["status"] == "paid":
                    logger.info("%s duplicate callback for paid order: %s", channel, order_no)
                    return {"order_no": order_no, "trade_no": trade_no}
                if row["status"] == "processing":
                    logger.warning("%s concurrent callback for processing order: %s", channel, order_no)
                    return None
                if row["status"] != "pending":
                    logger.warning("%s callback for non-pending order: %s status=%s", channel, order_no, row["status"])
                    return None

                await session.execute(
                    text("UPDATE orders SET status = 'processing', updated_at = NOW() WHERE order_no = :order_no"),
                    {"order_no": order_no},
                )

        return {"order_no": order_no, "trade_no": trade_no}


payment_service = PaymentService()
