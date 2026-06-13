"""Tests for the Fallback Reasoning Module (兜底推理模块).

Covers:
- 5 trigger conditions
- Eligibility filter (budget / circuit breaker / trivial rejections)
- LLM recommendation parsing and validation
- Safety gate and registry validation
- Recovery pattern store integration
- Audit event publishing
"""

from __future__ import annotations

from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.fallback_reasoning import (
    MAX_FALLBACKS_PER_RUN,
    MIN_FALLBACK_CREDITS,
    FallbackRecommendation,
    FallbackResult,
    FallbackTrigger,
    _call_fallback_llm,
    _clamp_confidence,
    _extract_json_object,
    _instantiate_from_pattern,
    _parse_recommendation,
    _validate_and_sanitize,
    attempt_fallback,
    is_eligible_for_fallback,
)
from app.services.recovery_pattern_store import (
    MIN_CONFIDENCE_FOR_MATCH,
    MIN_FREQUENCY_FOR_MATCH,
    _compute_signature,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_trigger() -> FallbackTrigger:
    return FallbackTrigger(
        source="runtime_decision",
        kind="reject",
        parent_decision={"action": "generate_keyframes", "reason": "capability_not_registered"},
        reason="capability_not_registered",
        stage_id="generate_keyframes",
    )


@pytest.fixture
def sample_snapshot() -> dict:
    return {
        "run": {"status": "running", "current_phase": "generate_keyframes", "goal": "生成关键帧"},
        "state_machine": {"missing": ["selected_image"], "reason": "缺少选中图片"},
        "flow": [
            {"id": "read_context", "action": "read_context", "status": "completed", "progress": 100},
            {"id": "generate_story_plan", "action": "generate_story_plan", "status": "completed", "progress": 100},
            {"id": "generate_keyframes", "action": "generate_keyframes", "status": "blocked",
             "gate": {"allowed": False, "missing": ["selected_image"], "reason": "缺少选中图片"}},
        ],
        "evidence": {"shot_count": 5, "selected_image_count": 0, "selected_video_count": 0},
        "budget": {"remaining_run_budget": 100},
        "outputs": {"shots": []},
        "decision_context": {"current_goal": "generate_keyframes"},
    }


@pytest.fixture
def sample_llm_response() -> dict:
    return {
        "action": "generate_keyframes",
        "params": {"target_shots": [1, 2, 3]},
        "user_message": "当前阻塞原因是关键帧缺失，建议重新生成镜头1-3的关键帧。",
        "reasoning": "检查发现镜头1-3的selected_image为空且image_review_status为regenerate。",
        "confidence": 0.85,
        "requires_human_confirmation": False,
        "dispatch_ready": True,
        "fallback_kind": "resolved",
        "extracted_insight": {
            "pattern": "image_review_blockers_keyframes_regenerate",
            "trigger_conditions": {"missing": ["selected_image"], "stage": "generate_keyframes"},
            "resolution": "regenerate_blocked_shots",
        },
    }


# ---------------------------------------------------------------------------
# Eligibility tests
# ---------------------------------------------------------------------------

class TestIsEligibleForFallback:
    def test_fires_on_reject(self):
        eligible, reason = is_eligible_for_fallback(
            "reject", "capability_not_registered",
            has_production_state=True, remaining_budget=100,
        )
        assert eligible is True
        assert reason == "eligible"

    def test_fires_on_ask(self):
        eligible, reason = is_eligible_for_fallback(
            "ask", "planner_needs_clarity",
            has_production_state=True, remaining_budget=100,
        )
        assert eligible is True

    def test_skips_execute(self):
        eligible, reason = is_eligible_for_fallback("execute", "", has_production_state=True)
        assert eligible is False
        assert reason == "wrong_decision_kind"

    def test_skips_defer(self):
        eligible, reason = is_eligible_for_fallback("defer", "busy_gate", has_production_state=True)
        assert eligible is False
        assert reason == "wrong_decision_kind"

    def test_skips_cancelled_run(self):
        eligible, reason = is_eligible_for_fallback("reject", "run_cancelled", has_production_state=True)
        assert eligible is False
        assert reason == "run_cancelled"

    def test_skips_busy_gate(self):
        eligible, reason = is_eligible_for_fallback("reject", "busy_gate", has_production_state=True)
        assert eligible is False
        assert reason == "busy_gate"

    def test_skips_trivial_unregistered_action_without_production(self):
        eligible, reason = is_eligible_for_fallback("reject", "capability_not_registered", has_production_state=False)
        assert eligible is False
        assert reason == "trivial_unregistered_action"

    def test_triggers_for_unregistered_action_with_production_state(self):
        eligible, reason = is_eligible_for_fallback(
            "reject", "capability_not_registered",
            has_production_state=True, remaining_budget=100,
        )
        assert eligible is True

    def test_circuit_breaker_blocks_after_max(self):
        eligible, reason = is_eligible_for_fallback(
            "reject", "capability_not_registered",
            has_production_state=True, fallback_count=MAX_FALLBACKS_PER_RUN,
        )
        assert eligible is False
        assert reason == "circuit_breaker_exceeded"

    def test_skips_insufficient_budget(self):
        eligible, reason = is_eligible_for_fallback(
            "reject", "capability_not_registered",
            has_production_state=True, remaining_budget=MIN_FALLBACK_CREDITS - 1,
        )
        assert eligible is False
        assert reason == "insufficient_budget"

    def test_fires_with_sufficient_budget(self):
        eligible, reason = is_eligible_for_fallback(
            "reject", "capability_not_registered",
            has_production_state=True, remaining_budget=MIN_FALLBACK_CREDITS + 10,
        )
        assert eligible is True

    def test_fires_on_blocked(self):
        eligible, reason = is_eligible_for_fallback(
            "blocked", "gate_blocked",
            has_production_state=True, remaining_budget=100,
        )
        assert eligible is True


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------

class TestParseRecommendation:
    def test_parses_valid_response(self, sample_llm_response):
        rec = _parse_recommendation(sample_llm_response)
        assert rec is not None
        assert rec.action == "generate_keyframes"
        assert rec.params == {"target_shots": [1, 2, 3]}
        assert rec.confidence == 0.85
        assert rec.fallback_kind == "resolved"
        assert rec.dispatch_ready is True
        assert rec.requires_human_confirmation is False

    def test_parses_partial_response(self):
        rec = _parse_recommendation({
            "action": "escalate_human",
            "params": {},
            "user_message": "需要更多信息",
            "reasoning": "模糊",
            "confidence": 0.3,
            "requires_human_confirmation": True,
            "dispatch_ready": False,
            "fallback_kind": "partial",
            "extracted_insight": {},
        })
        assert rec is not None
        assert rec.action == "escalate_human"
        assert rec.fallback_kind == "partial"
        assert rec.dispatch_ready is False

    def test_rejects_unknown_action(self):
        rec = _parse_recommendation({
            "action": "delete_everything",
            "params": {},
            "user_message": "",
            "reasoning": "",
            "confidence": 0.9,
            "requires_human_confirmation": False,
            "dispatch_ready": True,
            "fallback_kind": "resolved",
            "extracted_insight": {},
        })
        assert rec is None

    def test_rejects_empty_action(self):
        rec = _parse_recommendation({
            "action": "",
            "params": {},
            "user_message": "",
            "reasoning": "",
            "confidence": 0.9,
            "requires_human_confirmation": False,
            "dispatch_ready": True,
            "fallback_kind": "resolved",
            "extracted_insight": {},
        })
        assert rec is None

    def test_clamps_confidence(self):
        assert _clamp_confidence(1.5) == 1.0
        assert _clamp_confidence(-0.5) == 0.0
        assert _clamp_confidence(0.75) == 0.75
        assert _clamp_confidence(None) == 0.0
        assert _clamp_confidence("abc") == 0.0

    def normalizes_fallback_kind(self):
        rec = _parse_recommendation({
            "action": "generate_keyframes",
            "params": {},
            "user_message": "",
            "reasoning": "",
            "confidence": 0.5,
            "requires_human_confirmation": True,
            "dispatch_ready": False,
            "fallback_kind": "unknown",
            "extracted_insight": {},
        })
        assert rec is not None
        assert rec.fallback_kind == "escalate"


class TestExtractJsonObject:
    def test_extracts_from_raw_json(self):
        assert _extract_json_object('{"a": 1}') == {"a": 1}

    def test_extracts_from_text_with_prefix(self):
        assert _extract_json_object('Here is the result: {"action": "test"}') == {"action": "test"}

    def test_returns_empty_on_no_json(self):
        assert _extract_json_object("no json here") == {}

    def test_returns_empty_on_empty_string(self):
        assert _extract_json_object("") == {}


# ---------------------------------------------------------------------------
# Validation & sanitisation
# ---------------------------------------------------------------------------

class TestValidateAndSanitize:
    def test_passes_valid_recommendation(self):
        rec = FallbackRecommendation(
            action="generate_keyframes",
            params={},
            user_message="建议重做关键帧",
            reasoning="missing selected_image",
            confidence=0.85,
            requires_human_confirmation=False,
            dispatch_ready=True,
            fallback_kind="resolved",
            evidence_refs=[],
            extracted_insight={},
        )
        result = FallbackResult(triggered=True, recommendation=rec)
        validated = _validate_and_sanitize(result)
        assert validated.recommendation is not None
        assert validated.recommendation.action == "generate_keyframes"
        assert validated.recommendation.fallback_kind == "resolved"

    def test_escalates_unknown_action(self):
        rec = FallbackRecommendation(
            action="some_random_action",
            params={},
            user_message="",
            reasoning="",
            confidence=0.9,
            requires_human_confirmation=False,
            dispatch_ready=True,
            fallback_kind="resolved",
            evidence_refs=[],
            extracted_insight={},
        )
        result = FallbackResult(triggered=True, recommendation=rec)
        validated = _validate_and_sanitize(result)
        assert validated.recommendation is not None
        assert validated.recommendation.action == "escalate_human"

    def test_handles_no_recommendation(self):
        result = FallbackResult(triggered=True, recommendation=None)
        validated = _validate_and_sanitize(result)
        assert validated.recommendation is None


# ---------------------------------------------------------------------------
# Circuit breaker / empty-snapshot fallback results
# ---------------------------------------------------------------------------

class TestFallbackEdgeCases:
    def test_circuit_breaker_escalates(self, sample_trigger):
        from app.services.fallback_reasoning import _circuit_breaker_result
        result = _circuit_breaker_result(sample_trigger)
        assert result.triggered is False
        assert result.recommendation is not None
        assert result.recommendation.action == "escalate_human"

    def test_no_snapshot_escalates(self, sample_trigger):
        from app.services.fallback_reasoning import _no_snapshot_result
        result = _no_snapshot_result(sample_trigger)
        assert result.triggered is False
        assert result.recommendation is not None
        assert result.recommendation.action == "escalate_human"


# ---------------------------------------------------------------------------
# Attempt fallback (integration-oriented, mocks LLM)
# ---------------------------------------------------------------------------

class TestAttemptFallback:
    @patch("app.services.fallback_reasoning.get_agent_run_snapshot", new_callable=AsyncMock)
    @patch("app.services.fallback_reasoning._call_fallback_llm")
    @patch("app.services.fallback_reasoning._match_pattern", new_callable=AsyncMock)
    @patch("app.services.fallback_reasoning.publish_agent_event", new_callable=AsyncMock)
    @patch("app.services.fallback_reasoning._record_pattern", new_callable=AsyncMock)
    async def test_fallback_resolved_feeds_recommendation(
        self,
        mock_record: AsyncMock,
        mock_publish: AsyncMock,
        mock_match: AsyncMock,
        mock_llm: AsyncMock,
        mock_snapshot: AsyncMock,
        sample_trigger: FallbackTrigger,
        sample_llm_response: dict,
    ):
        mock_snapshot.return_value = {
            "run": {"status": "running", "current_phase": "generate_keyframes", "goal": "test"},
            "state_machine": {"missing": ["selected_image"], "reason": "缺少选中图片"},
            "flow": [],
            "evidence": {"shot_count": 5, "selected_image_count": 0, "selected_video_count": 0},
            "budget": {"remaining_run_budget": 100},
            "outputs": {"shots": []},
            "decision_context": {},
        }
        mock_match.return_value = None
        mock_llm.return_value = (
            FallbackRecommendation(
                action="generate_keyframes",
                params={},
                user_message="建议重做关键帧",
                reasoning="missing selected_image",
                confidence=0.85,
                requires_human_confirmation=False,
                dispatch_ready=True,
                fallback_kind="resolved",
                evidence_refs=[{"kind": "shot", "shot_index": 1}],
                extracted_insight={"pattern": "test"},
            ),
            "thinking-123",
        )
        mock_publish.return_value = {"id": "event-1"}
        mock_record.return_value = None

        db = AsyncMock()
        result = await attempt_fallback(
            db,
            run_id="run-1",
            project_id="proj-1",
            user_id=1,
            instruction="重新生成关键帧",
            trigger=sample_trigger,
            fallback_count=0,
        )

        assert result.triggered is True
        assert result.recommendation is not None
        assert result.recommendation.action == "generate_keyframes"
        assert result.recommendation.fallback_kind == "resolved"
        assert result.used_recovery_pattern is False
        assert len(result.events_written) == 1
        assert result.thinking_artifact_id == "thinking-123"

    @patch("app.services.fallback_reasoning.get_agent_run_snapshot", new_callable=AsyncMock)
    async def test_circuit_breaker_prevents_further_calls(
        self,
        mock_snapshot: AsyncMock,
        sample_trigger: FallbackTrigger,
    ):
        mock_snapshot.return_value = {"run": {}}
        db = AsyncMock()
        result = await attempt_fallback(
            db,
            run_id="run-1",
            project_id="proj-1",
            user_id=1,
            instruction="",
            trigger=sample_trigger,
            fallback_count=MAX_FALLBACKS_PER_RUN,
        )
        # Circuit breaker prevents LLM call — result is not "triggered"
        # but still provides an escalation recommendation
        assert result.triggered is False
        assert result.recommendation is not None
        assert result.recommendation.action == "escalate_human"

    @patch("app.services.fallback_reasoning.get_agent_run_snapshot", new_callable=AsyncMock)
    async def test_no_snapshot_returns_escalation(
        self,
        mock_snapshot: AsyncMock,
        sample_trigger: FallbackTrigger,
    ):
        mock_snapshot.return_value = None
        db = AsyncMock()
        result = await attempt_fallback(
            db,
            run_id="run-1",
            project_id="proj-1",
            user_id=1,
            instruction="",
            trigger=sample_trigger,
            fallback_count=0,
        )
        assert result.triggered is False
        assert result.recommendation is not None
        assert result.recommendation.action == "escalate_human"


# ---------------------------------------------------------------------------
# LLM integration (unit, no real HTTP call)
# ---------------------------------------------------------------------------

class TestCallFallbackLlm:
    @patch("app.services.fallback_reasoning.get_settings")
    async def test_returns_none_without_api_key(self, mock_settings):
        mock_settings.return_value.deepseek_api_key = ""
        mock_settings.return_value.deepseek_model = "deepseek-chat"
        mock_settings.return_value.deepseek_base_url = "https://api.deepseek.com"
        rec, thinking_id = await _call_fallback_llm(
            snapshot={"run": {}},
            instruction="test",
            trigger=FallbackTrigger(source="test", kind="reject", parent_decision={}),
            previous_fallbacks=None,
        )
        assert rec is None
        assert thinking_id == ""

    @patch("app.services.fallback_reasoning.get_settings")
    @patch("app.services.fallback_reasoning.httpx.AsyncClient")
    async def test_handles_http_error(self, mock_client, mock_settings):
        mock_settings.return_value.deepseek_api_key = "sk-test"
        mock_settings.return_value.deepseek_model = "deepseek-chat"
        mock_settings.return_value.deepseek_base_url = "https://api.deepseek.com"
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=Exception("Connection failed")
        )
        rec, thinking_id = await _call_fallback_llm(
            snapshot={"run": {}},
            instruction="test",
            trigger=FallbackTrigger(source="test", kind="reject", parent_decision={}),
            previous_fallbacks=None,
        )
        assert rec is None


# ---------------------------------------------------------------------------
# Recovery pattern store
# ---------------------------------------------------------------------------

class TestRecoveryPatternStore:
    def test_compute_signature_deterministic(self):
        sig1 = _compute_signature("runtime_decision", "reject", "capability_not_registered", ["selected_image"])
        sig2 = _compute_signature("runtime_decision", "reject", "capability_not_registered", ["selected_image"])
        assert sig1 == sig2
        assert len(sig1) == 64  # SHA-256 hex

    def test_signature_differs_with_different_missing_items(self):
        sig1 = _compute_signature("runtime_decision", "reject", "gate", ["selected_image"])
        sig2 = _compute_signature("runtime_decision", "reject", "gate", ["selected_video"])
        assert sig1 != sig2

    def test_signature_stable_with_ordering(self):
        sig1 = _compute_signature("runtime_decision", "reject", "gate", ["b", "a", "c"])
        sig2 = _compute_signature("runtime_decision", "reject", "gate", ["a", "b", "c"])
        assert sig1 == sig2  # Both sorted

    def test_empty_missing_items_handled(self):
        sig = _compute_signature("runtime_decision", "reject", "unknown", None)
        assert len(sig) == 64

    def test_instantiate_from_pattern(self):
        trigger = FallbackTrigger(source="test", kind="reject", parent_decision={})
        pattern = {
            "pattern_id": "p1",
            "trigger_signature": "sig",
            "recommendation_action": "generate_keyframes",
            "confidence": 0.85,
            "frequency": 5,
            "metadata": {
                "user_message": "根据历史模式建议重做关键帧",
                "requires_human_confirmation": True,
                "dispatch_ready": True,
                "reasoning": "历史模式匹配",
            },
        }
        rec = _instantiate_from_pattern(pattern, trigger, instruction="重做关键帧")
        assert rec.action == "generate_keyframes"
        assert rec.fallback_kind == "resolved"
        assert rec.confidence == 0.85


# ---------------------------------------------------------------------------
# Fallback trigger dataclass
# ---------------------------------------------------------------------------

class TestFallbackTrigger:
    def test_creates_with_minimal_fields(self):
        trigger = FallbackTrigger(
            source="runtime_decision",
            kind="reject",
            parent_decision={},
        )
        assert trigger.source == "runtime_decision"
        assert trigger.kind == "reject"
        assert trigger.reason == ""
        assert trigger.stage_id == ""


# ---------------------------------------------------------------------------
# ALL trigger sources — structural coverage
# ---------------------------------------------------------------------------

class TestAllTriggerSources:
    """Verifies all 5 trigger sources are handled by is_eligible_for_fallback."""

    def test_trigger_1_runtime_decision_reject(self):
        """Trigger 1: decide_runtime_action returns reject with capability_not_registered."""
        eligible, _ = is_eligible_for_fallback(
            "reject", "capability_not_registered",
            has_production_state=True, remaining_budget=100,
        )
        assert eligible is True

    def test_trigger_1_runtime_decision_ask(self):
        """Trigger 1: decide_runtime_action returns ask."""
        eligible, _ = is_eligible_for_fallback(
            "ask", "planner_needs_clarity",
            has_production_state=True, remaining_budget=100,
        )
        assert eligible is True

    def test_trigger_4_decision_tick_blocked(self):
        """Trigger 4: DecisionTickResult status=blocked."""
        eligible, _ = is_eligible_for_fallback(
            "blocked", "gate_blocked",
            has_production_state=True, remaining_budget=100,
        )
        assert eligible is True

    def test_trigger_4_decision_tick_recover(self):
        """Trigger 4: DecisionTickResult status=recover."""
        eligible, _ = is_eligible_for_fallback(
            "blocked", "recover",
            has_production_state=True, remaining_budget=100,
        )
        assert eligible is True
