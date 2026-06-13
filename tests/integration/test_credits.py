"""
P8-QA-5: 积分预扣/退款/回滚集成测试。

覆盖所有财务路径：
- reserve: 正常预扣、余额不足、账户不存在
- charge: 正常确认、幂等（重复 charge）、调整金额
- refund: 正常退款、幂等（重复 refund）、已 charge 不退
- 余额一致性：所有操作后 balance 与 credit_transactions 对账

注意：CreditService 内部用 AsyncSessionLocal 开独立连接，
      fixtures 必须提交数据（不能依赖 db_session 的未提交事务）。
"""
import uuid
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.services.auth import hash_password
from app.services.credits import (
    CreditService,
    InsufficientCreditsError,
    CreditAccountNotFoundError,
    UnknownCreditOperationError,
    CreditError,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_TEST_USER_IDS: list[int] = []


@pytest_asyncio.fixture
async def credit_user():
    """创建一个有 500 积分的测试用户（提交到 DB，测试后清理）。"""
    username = f"credit_test_{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            result = await s.execute(
                text("""
                    INSERT INTO users (username, email, password_hash, tier, status)
                    VALUES (:u, :e, :p, 'pro', 'active')
                    RETURNING id
                """),
                {"u": username, "e": f"{username}@qa.test", "p": hash_password("x")},
            )
            user_id = result.scalar()
            await s.execute(
                text("INSERT INTO credit_accounts (user_id, balance) VALUES (:uid, 500)"),
                {"uid": user_id},
            )
    _TEST_USER_IDS.append(user_id)
    yield user_id
    # 清理
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text("DELETE FROM credit_transactions WHERE user_id = :uid"), {"uid": user_id}
            )
            await s.execute(
                text("DELETE FROM credit_accounts WHERE user_id = :uid"), {"uid": user_id}
            )
            await s.execute(
                text("DELETE FROM users WHERE id = :uid"), {"uid": user_id}
            )


@pytest_asyncio.fixture
async def credit_pricing():
    """插入测试用定价（image_gen = 2 积分），测试后恢复。"""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            existing = (await s.execute(
                text("SELECT credits_cost FROM credit_pricing WHERE operation = 'image_gen'"),
            )).first()
            await s.execute(
                text("""
                    INSERT INTO credit_pricing (operation, credits_cost, active)
                    VALUES ('image_gen', 2, TRUE)
                    ON CONFLICT (operation) DO UPDATE SET credits_cost = 2, active = TRUE
                """),
            )
    yield
    if existing is None:
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(
                    text("DELETE FROM credit_pricing WHERE operation = 'image_gen'"),
                )
    else:
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(
                    text("UPDATE credit_pricing SET credits_cost = :c WHERE operation = 'image_gen'"),
                    {"c": existing[0]},
                )


# ─── reserve ────────────────────────────────────────────────────────────────────

class TestCreditReserve:

    async def test_reserve_deducts_balance(self, credit_user, credit_pricing):
        svc = CreditService()
        tx_id = await svc._reserve(credit_user, "image_gen", 1)
        assert tx_id

        from app.db import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            row = (await s.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": credit_user},
            )).first()
        assert row[0] == 498  # 500 - 2

    async def test_reserve_insufficient_balance_raises(self, credit_user, credit_pricing):
        svc = CreditService()
        with pytest.raises(InsufficientCreditsError):
            await svc._reserve(credit_user, "image_gen", 300)  # 300 * 2 = 600 > 500

    async def test_reserve_unknown_operation_raises(self, credit_user):
        svc = CreditService()
        with pytest.raises(UnknownCreditOperationError):
            await svc._reserve(credit_user, "nonexistent_op", 1)

    async def test_reserve_missing_account_raises(self):
        svc = CreditService()
        with pytest.raises((CreditAccountNotFoundError, Exception)):
            await svc._reserve(999999, "image_gen", 1)

    async def test_reserve_creates_transaction_record(self, credit_user, credit_pricing):
        svc = CreditService()
        tx_id = await svc._reserve(credit_user, "image_gen", 1)

        from app.db import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            row = (await s.execute(
                text("""
                    SELECT tx_type, amount FROM credit_transactions
                    WHERE reference_id = :ref AND tx_type = 'reserve'
                """),
                {"ref": tx_id},
            )).first()
        assert row is not None
        assert row[0] == "reserve"
        assert row[1] == -2  # 扣 2 积分


# ─── charge ─────────────────────────────────────────────────────────────────────

class TestCreditCharge:

    async def test_charge_same_amount_no_balance_change(self, credit_user, credit_pricing):
        """charge 金额等于 reserve 金额时，余额不再变化。"""
        svc = CreditService()
        tx_id = await svc._reserve(credit_user, "image_gen", 1)

        from app.db import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            before = (await s.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": credit_user},
            )).scalar()

        await svc._charge(tx_id, actual_amount=None)

        async with AsyncSessionLocal() as s:
            after = (await s.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": credit_user},
            )).scalar()

        assert after == before  # reserve 已扣，charge 不再扣

    async def test_charge_idempotent(self, credit_user, credit_pricing):
        """重复 charge 同一 tx_id 幂等，余额不变。"""
        svc = CreditService()
        tx_id = await svc._reserve(credit_user, "image_gen", 1)
        await svc._charge(tx_id)

        from app.db import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            balance_1 = (await s.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": credit_user},
            )).scalar()

        await svc._charge(tx_id)  # 第二次 charge

        async with AsyncSessionLocal() as s:
            balance_2 = (await s.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": credit_user},
            )).scalar()

        assert balance_1 == balance_2

    async def test_charge_adjusted_amount(self, credit_user, credit_pricing):
        """charge 可以调整实际金额（少于 reserve）。"""
        svc = CreditService()
        tx_id = await svc._reserve(credit_user, "image_gen", 1)  # reserve 2

        from app.db import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            before = (await s.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": credit_user},
            )).scalar()

        await svc._charge(tx_id, actual_amount=1)  # 实际只扣 1，退还 1

        async with AsyncSessionLocal() as s:
            after = (await s.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": credit_user},
            )).scalar()

        assert after == before + 1  # 退还 1 积分


# ─── refund ──────────────────────────────────────────────────────────────────────

class TestCreditRefund:

    async def test_refund_restores_balance(self, credit_user, credit_pricing):
        svc = CreditService()
        tx_id = await svc._reserve(credit_user, "image_gen", 1)

        from app.db import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            before_reserve = (await s.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": credit_user},
            )).scalar()

        refunded = await svc._refund(tx_id)
        assert refunded == 2

        async with AsyncSessionLocal() as s:
            after_refund = (await s.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": credit_user},
            )).scalar()

        assert after_refund == before_reserve + 2

    async def test_refund_idempotent(self, credit_user, credit_pricing):
        """重复 refund 幂等，余额不变。"""
        svc = CreditService()
        tx_id = await svc._reserve(credit_user, "image_gen", 1)
        await svc._refund(tx_id)

        from app.db import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            balance_1 = (await s.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": credit_user},
            )).scalar()

        await svc._refund(tx_id)  # 第二次 refund

        async with AsyncSessionLocal() as s:
            balance_2 = (await s.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": credit_user},
            )).scalar()

        assert balance_1 == balance_2

    async def test_refund_after_charge_returns_zero(self, credit_user, credit_pricing):
        """已 charge 的 tx_id 调用 refund 返回 0（不退款）。"""
        svc = CreditService()
        tx_id = await svc._reserve(credit_user, "image_gen", 1)
        await svc._charge(tx_id)
        refunded = await svc._refund(tx_id)
        assert refunded == 0

    async def test_refund_creates_transaction_record(self, credit_user, credit_pricing):
        svc = CreditService()
        tx_id = await svc._reserve(credit_user, "image_gen", 1)
        await svc._refund(tx_id)

        from app.db import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            row = (await s.execute(
                text("""
                    SELECT tx_type, amount FROM credit_transactions
                    WHERE reference_id = :ref AND tx_type = 'refund'
                """),
                {"ref": tx_id},
            )).first()
        assert row is not None
        assert row[1] == 2  # 退还 2 积分（正数）


# ─── 余额一致性 ──────────────────────────────────────────────────────────────────

class TestCreditConsistency:

    async def test_balance_matches_transaction_sum(self, credit_user, credit_pricing):
        """balance = 初始余额 + sum(credit_transactions.amount)。"""
        svc = CreditService()

        # 执行一系列操作
        tx1 = await svc._reserve(credit_user, "image_gen", 2)  # -4
        tx2 = await svc._reserve(credit_user, "image_gen", 1)  # -2
        await svc._charge(tx1)                                  # 0 delta
        await svc._refund(tx2)                                  # +2

        from app.db import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            balance = (await s.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": credit_user},
            )).scalar()

            tx_sum = (await s.execute(
                text("SELECT COALESCE(SUM(amount), 0) FROM credit_transactions WHERE user_id = :uid"),
                {"uid": credit_user},
            )).scalar()

        # 初始 500 + 所有交易 = 当前余额
        assert 500 + int(tx_sum) == int(balance)
