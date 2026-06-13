"""Credit service — atomic reserve / charge / refund with Pydantic models.

Re-exports ``CreditService`` and error classes for convenience.
"""

from app.services.credits.service import (
    CreditAccountNotFoundError,
    CreditError,
    CreditService,
    DEFAULT_PRICING,
    InsufficientCreditsError,
    UnknownCreditOperationError,
)
from app.db import AsyncSessionLocal as _session_factory

__all__ = [
    "CreditService",
    "CreditError",
    "InsufficientCreditsError",
    "CreditAccountNotFoundError",
    "UnknownCreditOperationError",
    "DEFAULT_PRICING",
    "credit_service",
]

credit_service = CreditService(session_factory=_session_factory)
