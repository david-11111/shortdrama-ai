from datetime import datetime

from pydantic import BaseModel


class CreditBalanceResponse(BaseModel):
    balance: int
    lifetime_earned: int
    lifetime_spent: int


class CreditTransaction(BaseModel):
    amount: int
    balance_after: int
    tx_type: str
    reference_id: str | None
    description: str | None
    created_at: datetime


class CreditTransactionsResponse(BaseModel):
    transactions: list[CreditTransaction]
    page: int
    page_size: int


class CreditPricing(BaseModel):
    operation: str
    credits_cost: int
    tier_overrides: dict | None


class CreditPricingResponse(BaseModel):
    pricing: list[CreditPricing]
