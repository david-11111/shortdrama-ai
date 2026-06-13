from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCategory(StrEnum):
    BACKPRESSURE = "backpressure"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    PROVIDER = "provider"
    POLICY = "policy"
    STORAGE = "storage"
    CREDIT = "credit"
    VALIDATION = "validation"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ErrorDecision:
    category: ErrorCategory
    retryable: bool
    report_to_key_pool: bool
    dead_letter: bool
    reason: str


_RETRYABLE_TOKENS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "timeout",
    "timed out",
    "temporar",
    "connection",
    "connect",
    "quota",
    "rate",
    "too many requests",
    "backpressure",
    "saturated",
    "broker",
    "redis",
)

_NON_RETRYABLE_TOKENS = (
    "validation",
    "invalid payload",
    "bad request",
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "not configured",
    "not implemented",
    "insufficient credits",
    "missing credit",
    "policy violation",
    "content policy",
)


def classify_exception(error: BaseException) -> ErrorDecision:
    text = _error_text(error)
    category = _classify_category(error, text)

    retryable = _is_retryable(category, text)
    report_to_key_pool = category in {
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.TIMEOUT,
        ErrorCategory.NETWORK,
        ErrorCategory.PROVIDER,
    }
    dead_letter = retryable
    if category in {
        ErrorCategory.POLICY,
        ErrorCategory.VALIDATION,
        ErrorCategory.CONFIGURATION,
        ErrorCategory.CREDIT,
    }:
        dead_letter = False

    return ErrorDecision(
        category=category,
        retryable=retryable,
        report_to_key_pool=report_to_key_pool,
        dead_letter=dead_letter,
        reason=_reason(category, retryable, text),
    )


def is_retryable_exception(error: BaseException) -> bool:
    return classify_exception(error).retryable


def _error_text(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}".lower()


def _classify_category(error: BaseException, text: str) -> ErrorCategory:
    name = type(error).__name__.lower()
    if "backpressure" in name or "backpressure" in text or "saturated" in text:
        return ErrorCategory.BACKPRESSURE
    if isinstance(error, TimeoutError) or "timeout" in text or "timed out" in text:
        return ErrorCategory.TIMEOUT
    if "policy" in name or "policy violation" in text or "content policy" in text:
        return ErrorCategory.POLICY
    if "credit" in name or "insufficient credits" in text or "missing credit" in text:
        return ErrorCategory.CREDIT
    if "validation" in name or "invalid payload" in text or "bad request" in text:
        return ErrorCategory.VALIDATION
    if "not configured" in text or "not implemented" in text:
        return ErrorCategory.CONFIGURATION
    if "storage" in name or "oss" in text or "s3" in text or "upload" in text:
        return ErrorCategory.STORAGE
    if "429" in text or "rate" in text or "too many requests" in text or "quota" in text:
        return ErrorCategory.RATE_LIMIT
    if "connection" in text or "connect" in text or "network" in text or "dns" in text:
        return ErrorCategory.NETWORK
    if "provider" in text or "seedream" in text or "seedance" in text or "kling" in text:
        return ErrorCategory.PROVIDER
    return ErrorCategory.UNKNOWN


def _is_retryable(category: ErrorCategory, text: str) -> bool:
    if any(token in text for token in _NON_RETRYABLE_TOKENS):
        return False
    if category in {
        ErrorCategory.BACKPRESSURE,
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.TIMEOUT,
        ErrorCategory.NETWORK,
        ErrorCategory.STORAGE,
    }:
        return True
    if category == ErrorCategory.PROVIDER:
        return any(token in text for token in _RETRYABLE_TOKENS)
    if category == ErrorCategory.UNKNOWN:
        return any(token in text for token in _RETRYABLE_TOKENS)
    return False


def _reason(category: ErrorCategory, retryable: bool, text: str) -> str:
    if retryable:
        return f"{category.value}: retryable transient failure"
    if category == ErrorCategory.UNKNOWN:
        return "unknown: non-retryable by policy"
    return f"{category.value}: non-retryable failure"
