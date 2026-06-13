"""
Verify payment callback success path for tier upgrade.

What this script does:
1. Create a temporary user + credit account + pending tier-upgrade order.
2. Call /api/payment/callback/alipay with mocked verify_alipay_callback success.
3. Query DB to confirm:
   - order status -> paid
   - user tier/tier_expires_at updated
   - credit_transactions bonus row exists
4. Print JSON evidence and clean up temporary rows.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import uuid
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main_module
from app.db import AsyncSessionLocal
from app.services.auth import hash_password


async def _create_test_data() -> tuple[int, str]:
    email = f"upgrade_verify_{uuid.uuid4().hex[:8]}@qa.test"
    order_no = f"ORD_UPG_VERIFY_{uuid.uuid4().hex[:10].upper()}"

    async with AsyncSessionLocal() as session:
        async with session.begin():
            user_result = await session.execute(
                text(
                    """
                    INSERT INTO users (email, password_hash, display_name, tier, status)
                    VALUES (:email, :password_hash, :display_name, 'free', 'active')
                    RETURNING id
                    """
                ),
                {
                    "email": email,
                    "password_hash": hash_password("TestPass123!"),
                    "display_name": "upgrade_verify",
                },
            )
            user_id = int(user_result.scalar_one())

            await session.execute(
                text("INSERT INTO credit_accounts (user_id, balance) VALUES (:user_id, 50)"),
                {"user_id": user_id},
            )

            await session.execute(
                text(
                    """
                    INSERT INTO orders (
                        order_no, user_id, amount_cents, credits, payment_method, status,
                        order_type, plan_id, tier_target, tier_days
                    )
                    VALUES (
                        :order_no, :user_id, 2900, 0, 'alipay', 'pending',
                        'tier_upgrade', 'pro_month', 'pro', 30
                    )
                    """
                ),
                {"order_no": order_no, "user_id": user_id},
            )

    return user_id, order_no


async def _cleanup(user_id: int, order_no: str) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM credit_transactions WHERE description LIKE :d"),
                {"d": f"%{order_no}%"},
            )
            await session.execute(text("DELETE FROM orders WHERE order_no = :o"), {"o": order_no})
            await session.execute(text("DELETE FROM credit_accounts WHERE user_id = :u"), {"u": user_id})
            await session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})


async def main() -> None:
    user_id, order_no = await _create_test_data()
    evidence: dict[str, object] = {}
    try:
        with patch(
            "app.services.payment.payment_service.verify_alipay_callback",
            new=AsyncMock(return_value={"order_no": order_no, "trade_no": "ALI_VERIFY_OK_001"}),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=main_module.app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/payment/callback/alipay",
                    data={"trade_status": "TRADE_SUCCESS"},
                )
        evidence["callback_http_status"] = resp.status_code
        evidence["callback_body"] = resp.text

        async with AsyncSessionLocal() as session:
            order_row = (
                await session.execute(
                    text(
                        """
                        SELECT order_no, order_type, status, trade_no, paid_at, tier_target, tier_days
                        FROM orders
                        WHERE order_no = :order_no
                        """
                    ),
                    {"order_no": order_no},
                )
            ).mappings().first()
            user_row = (
                await session.execute(
                    text("SELECT id, tier, tier_expires_at FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )
            ).mappings().first()
            tx_row = (
                await session.execute(
                    text(
                        """
                        SELECT user_id, amount, balance_after, tx_type, description
                        FROM credit_transactions
                        WHERE description LIKE :d
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"d": f"%{order_no}%"},
                )
            ).mappings().first()

        evidence["order_after_callback"] = dict(order_row) if order_row else None
        evidence["user_after_callback"] = dict(user_row) if user_row else None
        evidence["bonus_tx_after_callback"] = dict(tx_row) if tx_row else None
        print(json.dumps(evidence, ensure_ascii=False, default=str, indent=2))
    finally:
        await _cleanup(user_id, order_no)


if __name__ == "__main__":
    asyncio.run(main())
