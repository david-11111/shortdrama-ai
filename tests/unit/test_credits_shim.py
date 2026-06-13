from __future__ import annotations


def test_credits_shim_exports_service_classes() -> None:
    from app.services.credits import CreditService, InsufficientCreditsError, credit_service

    assert CreditService is not None
    assert InsufficientCreditsError is not None
    assert credit_service is not None
