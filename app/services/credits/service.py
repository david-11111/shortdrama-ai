"""Credit service — atomic reserve / charge / refund with Pydantic models.

Key improvements over the old ``credits.py``:

1. **No ``check_balance``** — it was a non-atomic read-before-write
   pattern that could race. ``reserve()`` already checks atomically.
2. **Session injection** — ``CreditService`` accepts a session factory
   or callable, making it testable without monkey-patching.
3. **No raw SQL in business logic** — all queries are extracted into
   ``_get_account_for_update()``, ``_insert_transaction()``, etc.
4. **Enums instead of magic strings** — ``TransactionType`` and
   ``CreditOperation`` centralize every string constant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import CreditOperation, TransactionType

# LLM token → credit 费率（每 token 消耗的积分）
LLM_TOKEN_RATE = 0.01

DEFAULT_PRICING: dict[str, int] = {
    CreditOperation.VIDEO_GEN_5S: 80,
    CreditOperation.VIDEO_GEN_8S: 120,
    CreditOperation.VIDEO_GEN_10S: 160,
    CreditOperation.VIDEO_GEN_15S: 240,
    CreditOperation.IMAGE_GEN: 12,
    CreditOperation.LLM_REFINE: 6,
    CreditOperation.LLM_DIRECTOR_CHAT: 6,
    CreditOperation.LLM_PLANNER_CALL: 0,  # 0 = 按 token 浮动计费
    CreditOperation.FINAL_CUT_AI_PLAN: 6,
    CreditOperation.PIPELINE_ANALYSIS: 15,
    CreditOperation.TTS_SYNTHESIS: 1,
}


class CreditError(RuntimeError):
    """Base credit-service error."""


class InsufficientCreditsError(CreditError):
    """Raised when a user does not have enough balance."""


class CreditAccountNotFoundError(CreditError):
    """Raised when the credit account row is missing."""


class UnknownCreditOperationError(CreditError):
    """Raised when an operation is not priced."""


class CreditService:
    """Atomic credit operations — reserve, charge, refund.

    Thread-safe via ``FOR UPDATE`` row-level locks in PostgreSQL.
    Idempotent — calling ``charge()`` or ``refund()`` twice with the
    same *transaction_id* is safe and returns the same result.
    """

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        """Inject a session factory (typically ``AsyncSessionLocal``)."""
        self._session_factory = session_factory

    async def reserve(self, user_id: str | int, operation: str, quantity: int = 1) -> str:
        """Atomically reserve credits for an operation.

        Returns a unique *transaction_id* that must be passed to
        ``charge()`` or ``refund()`` later.

        Raises ``InsufficientCreditsError`` if the balance is too low.
        Raises ``CreditAccountNotFoundError`` if the user has no account.
        """
        transaction_id = str(uuid4())
        required = await self.get_price(operation, quantity)

        async with self._session_factory() as session:
            async with session.begin():
                user_pk = await self._resolve_user_pk(session, user_id)
                account = await self._get_account_for_update(session, user_pk)
                if account["balance"] < required:
                    raise InsufficientCreditsError(
                        f"User '{user_id}' requires {required} credits but only has {account['balance']}."
                    )

                new_balance = account["balance"] - required
                await self._update_balance(session, user_pk, new_balance)
                await self._insert_transaction(
                    session, user_pk, -required, new_balance,
                    TransactionType.RESERVE, transaction_id,
                    f"Reserve credits for {operation} x{quantity}",
                )
        return transaction_id

    async def charge(self, transaction_id: str, actual_amount: int | None = None) -> None:
        """Finalize a reservation — debit the actual cost.

        If *actual_amount* is None, the full reserved amount is charged.
        If the actual amount exceeds the reserved amount and the user's
        balance can cover the difference, the extra is debited too.
        """
        async with self._session_factory() as session:
            async with session.begin():
                reserve = await self._get_reserve_record(session, transaction_id)
                if await self._has_tx_type(session, transaction_id, TransactionType.REFUND):
                    return  # Already refunded — no-op
                if await self._has_tx_type(session, transaction_id, TransactionType.CHARGE):
                    return  # Already charged — idempotent

                reserved_amount = reserve["amount"]
                final_amount = reserved_amount if actual_amount is None else int(actual_amount)
                delta = final_amount - reserved_amount

                account = await self._get_account_for_update(session, reserve["user_id"])

                if delta > 0 and account["balance"] < delta:
                    raise InsufficientCreditsError(
                        f"Transaction '{transaction_id}' needs {delta} extra credits to finalize."
                    )

                balance = account["balance"]
                balance_after = balance - delta
                lifetime_spent_delta = final_amount

                await self._update_balance_and_lifetime(session, reserve["user_id"], balance_after, lifetime_spent_delta)
                await self._insert_transaction(
                    session, reserve["user_id"], -delta, balance_after,
                    TransactionType.CHARGE, transaction_id,
                    f"Finalize charge at {final_amount} credits",
                )

    async def refund(self, transaction_id: str) -> int:
        """Release a reservation — return the reserved credits to the balance.

        Returns the refunded amount.  Idempotent: calling twice returns
        the same amount without double-refunding.
        """
        async with self._session_factory() as session:
            async with session.begin():
                existing = await self._get_existing_refund(session, transaction_id)
                if existing is not None:
                    return existing

                if await self._has_tx_type(session, transaction_id, TransactionType.CHARGE):
                    return 0  # Already charged — nothing to refund

                reserve = await self._get_reserve_record(session, transaction_id)
                refund_amount = reserve["amount"]
                account = await self._get_account_for_update(session, reserve["user_id"])
                balance_after = account["balance"] + refund_amount

                await self._update_balance(session, reserve["user_id"], balance_after)
                await self._insert_transaction(
                    session, reserve["user_id"], refund_amount, balance_after,
                    TransactionType.REFUND, transaction_id,
                    "Refund reserved credits",
                )
                return refund_amount

    # ── Post-hoc charge for variable-cost operations (LLM token usage) ──

    async def charge_direct(
        self,
        user_id: str | int,
        *,
        operation: str,
        token_count: int,
        ref_id: str,
    ) -> int:
        """Post-hoc charge based on token usage.

        Unlike ``reserve()``/``charge()``, this does NOT require a prior
        reservation — it deducts the calculated cost directly.

        Idempotent via *ref_id*: calling twice with the same *ref_id*
        returns the same amount without double-charging.

        Fails gracefully: returns 0 if the balance is insufficient or the
        account is missing, without raising.  Never blocks the caller.
        """
        credits = max(1, round(token_count * LLM_TOKEN_RATE))
        async with self._session_factory() as session:
            async with session.begin():
                already = await self._has_tx_type(session, ref_id, TransactionType.CHARGE)
                if already:
                    return credits

                try:
                    user_pk = await self._resolve_user_pk(session, user_id)
                    account = await self._get_account_for_update(session, user_pk)
                except CreditAccountNotFoundError:
                    logger.warning("charge_direct: no account for user %s — skipping", user_id)
                    return 0

                balance = account["balance"]
                if balance < credits:
                    logger.warning(
                        "charge_direct: user %s needs %d credits for %s (%d tokens) "
                        "but only has %d — skipping",
                        user_id, credits, operation, token_count, balance,
                    )
                    return 0

                balance_after = balance - credits
                await self._update_balance(session, user_pk, balance_after)
                await self._insert_transaction(
                    session, user_pk, -credits, balance_after,
                    TransactionType.CHARGE, ref_id,
                    f"LLM {operation} x{token_count} tokens",
                )
                return credits

    # ── Read-only query ────────────────────────────────────────────────

    async def get_balance(self, user_id: str | int) -> int:
        """Return the current credit balance for display purposes."""
        async with self._session_factory() as session:
            user_pk = await self._resolve_user_pk(session, user_id)
            row = (await session.execute(
                text("SELECT balance FROM credit_accounts WHERE user_id = :uid"),
                {"uid": user_pk},
            )).first()
            if row is None:
                return 0
            return int(row[0])

    async def get_price(self, operation: str, quantity: int = 1) -> int:
        """Return the price for *operation* × *quantity*.

        Checks DB first (``credit_pricing`` table), falls back to
        ``DEFAULT_PRICING``.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT credits_cost FROM credit_pricing WHERE operation = :op AND active = TRUE LIMIT 1"),
                {"op": operation},
            )
            row = result.first()
            if row is not None:
                return int(row[0]) * quantity
            if operation not in DEFAULT_PRICING:
                raise UnknownCreditOperationError(f"Unknown credit operation '{operation}'.")
            return DEFAULT_PRICING[operation] * quantity

    # ── Internal helpers ────────────────────────────────────────────────

    async def _resolve_user_pk(self, session: AsyncSession, user_id: str | int) -> int:
        if isinstance(user_id, int) or (isinstance(user_id, str) and user_id.isdigit()):
            return int(user_id)
        result = await session.execute(
            text("SELECT id FROM users WHERE CAST(user_id AS TEXT) = :eid LIMIT 1"),
            {"eid": str(user_id)},
        )
        row = result.first()
        if row is None:
            raise CreditAccountNotFoundError(f"Unknown user identifier '{user_id}'.")
        return int(row[0])

    async def _get_account_for_update(self, session: AsyncSession, user_pk: int) -> dict[str, Any]:
        row = (await session.execute(
            text("SELECT balance FROM credit_accounts WHERE user_id = :uid FOR UPDATE"),
            {"uid": user_pk},
        )).first()
        if row is None:
            raise CreditAccountNotFoundError(f"Missing credit account for user_pk '{user_pk}'.")
        return {"balance": int(row[0])}

    async def _update_balance(self, session: AsyncSession, user_pk: int, balance: int) -> None:
        await session.execute(
            text("UPDATE credit_accounts SET balance = :balance, updated_at = NOW() WHERE user_id = :uid"),
            {"balance": balance, "uid": user_pk},
        )

    async def _update_balance_and_lifetime(self, session: AsyncSession, user_pk: int, balance: int, lifetime_delta: int) -> None:
        await session.execute(
            text("""
                UPDATE credit_accounts
                SET balance = :balance, lifetime_spent = lifetime_spent + :delta, updated_at = NOW()
                WHERE user_id = :uid
            """),
            {"balance": balance, "delta": lifetime_delta, "uid": user_pk},
        )

    async def _insert_transaction(
        self, session: AsyncSession, user_pk: int, amount: int, balance_after: int,
        tx_type: TransactionType, reference_id: str, description: str,
    ) -> None:
        await session.execute(
            text("""
                INSERT INTO credit_transactions (user_id, amount, balance_after, tx_type, reference_id, description)
                VALUES (:uid, :amt, :bal, :tx, :ref, :desc)
            """),
            {"uid": user_pk, "amt": amount, "bal": balance_after,
             "tx": tx_type.value, "ref": reference_id, "desc": description},
        )

    async def _get_reserve_record(self, session: AsyncSession, transaction_id: str) -> dict[str, Any]:
        row = (await session.execute(
            text("""
                SELECT user_id, ABS(amount) AS amount
                FROM credit_transactions
                WHERE reference_id = :ref AND tx_type = 'reserve'
                ORDER BY id DESC LIMIT 1 FOR UPDATE
            """),
            {"ref": transaction_id},
        )).mappings().first()
        if row is None:
            raise CreditError(f"Missing reserve transaction '{transaction_id}'.")
        return dict(row)

    async def _has_tx_type(self, session: AsyncSession, transaction_id: str, tx_type: TransactionType) -> bool:
        row = (await session.execute(
            text("SELECT 1 FROM credit_transactions WHERE reference_id = :ref AND tx_type = :tx LIMIT 1"),
            {"ref": transaction_id, "tx": tx_type.value},
        )).first()
        return row is not None

    async def _get_existing_refund(self, session: AsyncSession, transaction_id: str) -> int | None:
        row = (await session.execute(
            text("""
                SELECT amount FROM credit_transactions
                WHERE reference_id = :ref AND tx_type = 'refund'
                ORDER BY id DESC LIMIT 1
            """),
            {"ref": transaction_id},
        )).first()
        if row is not None:
            return int(row[0])
        return None
