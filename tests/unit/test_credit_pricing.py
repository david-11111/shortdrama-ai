"""
单元测试 — CreditService 定价逻辑（不依赖 DB）。
"""
import pytest

from app.services.credits import (
    DEFAULT_PRICING,
    CreditAccountNotFoundError,
    CreditError,
    InsufficientCreditsError,
    UnknownCreditOperationError,
)

pytestmark = [pytest.mark.unit]


class TestDefaultPricing:
    """DEFAULT_PRICING 硬编码定价表覆盖。"""

    def test_known_operations_have_prices(self):
        expected = {
            "video_gen_5s", "video_gen_8s", "video_gen_10s", "video_gen_15s",
            "image_gen", "llm_refine", "llm_director_chat",
            "final_cut_ai_plan", "pipeline_analysis", "tts_synthesis",
        }
        assert expected.issubset({str(key) for key in DEFAULT_PRICING.keys()})

    def test_all_prices_positive(self):
        for op, price in DEFAULT_PRICING.items():
            if str(op) == "llm_planner_call":
                assert price == 0
                continue
            assert price > 0, f"{op} has non-positive price {price}"

    def test_video_prices_ordered(self):
        assert DEFAULT_PRICING["video_gen_5s"] < DEFAULT_PRICING["video_gen_8s"]
        assert DEFAULT_PRICING["video_gen_8s"] < DEFAULT_PRICING["video_gen_10s"]
        assert DEFAULT_PRICING["video_gen_10s"] < DEFAULT_PRICING["video_gen_15s"]


class TestCreditServiceErrors:
    """错误类层次结构。"""

    def test_insufficient_credits_is_credit_error(self):
        assert issubclass(InsufficientCreditsError, CreditError)

    def test_account_not_found_is_credit_error(self):
        assert issubclass(CreditAccountNotFoundError, CreditError)

    def test_unknown_operation_is_credit_error(self):
        assert issubclass(UnknownCreditOperationError, CreditError)
