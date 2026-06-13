from app.services.error_policy import ErrorCategory, classify_exception, is_retryable_exception


class BackpressureError(RuntimeError):
    pass


class PolicyViolationError(RuntimeError):
    pass


class InsufficientCreditsError(RuntimeError):
    pass


def test_backpressure_is_retryable_dead_letter_candidate():
    decision = classify_exception(BackpressureError("service saturated"))

    assert decision.category == ErrorCategory.BACKPRESSURE
    assert decision.retryable is True
    assert decision.dead_letter is True
    assert is_retryable_exception(BackpressureError("service saturated")) is True


def test_policy_violation_is_not_retryable():
    decision = classify_exception(PolicyViolationError("content policy violation"))

    assert decision.category == ErrorCategory.POLICY
    assert decision.retryable is False
    assert decision.dead_letter is False


def test_credit_error_is_not_retryable():
    decision = classify_exception(InsufficientCreditsError("insufficient credits"))

    assert decision.category == ErrorCategory.CREDIT
    assert decision.retryable is False
    assert decision.dead_letter is False


def test_timeout_is_retryable_and_reported_to_key_pool():
    decision = classify_exception(TimeoutError("provider timed out"))

    assert decision.category == ErrorCategory.TIMEOUT
    assert decision.retryable is True
    assert decision.report_to_key_pool is True


def test_configuration_error_is_not_retryable():
    decision = classify_exception(RuntimeError("WeChat Pay native order signing is not implemented"))

    assert decision.category == ErrorCategory.CONFIGURATION
    assert decision.retryable is False
    assert decision.dead_letter is False
