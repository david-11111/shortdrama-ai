import pytest

from app.services.agent_runtime_contracts import (
    ARTIFACT_REQUIREMENTS,
    CAPABILITY_REQUIREMENTS,
    DANGEROUS_ACTIONS,
    RISK_THRESHOLDS,
    ArtifactRef,
    CapabilityViolation,
    DecisionMailboxRecord,
    ExpectedArtifact,
    ObservationSignal,
    RuntimeFeedback,
    SafetyReviewRequired,
    ensure_lane_can,
    ensure_runtime_requirements,
    ensure_safety_gate,
    expected_artifacts_for_action,
    normalize_signal_severity,
)


def test_b_lane_cannot_execute_provider_work():
    with pytest.raises(CapabilityViolation, match="b_lane_agent_runs cannot execute"):
        ensure_lane_can("b_lane_agent_runs", "execute")


def test_c_lane_cannot_choose_global_next_action():
    with pytest.raises(CapabilityViolation, match="c_lane_production cannot choose_next_global_action"):
        ensure_lane_can("c_lane_production", "choose_next_global_action")


def test_c_lane_can_execute_assigned_mission():
    ensure_lane_can("c_lane_production", "execute_assigned_mission")


def test_observation_signal_as_dict_has_stable_shape():
    signal = ObservationSignal(
        type="WRITEBACK_FAILED",
        severity="error",
        source="writeback_status",
        run_id="run-1",
        task_id="task-1",
        stage_id="generate_keyframes",
        summary="Task completed but selected_image was not written back.",
        evidence_refs=[{"kind": "shot_row", "shot_index": 1}],
        suggested_recovery="repair_writeback",
    )

    payload = signal.as_dict()

    assert payload["type"] == "WRITEBACK_FAILED"
    assert payload["severity"] == "error"
    assert payload["suggested_recovery"] == "repair_writeback"


def test_runtime_feedback_as_dict_defaults():
    feedback = RuntimeFeedback(
        status="executing",
        summary="Generating video for shot 1.",
        next_step="Wait for task completion.",
    )

    payload = feedback.as_dict()

    assert payload["status"] == "executing"
    assert payload["requires_user"] is False
    assert payload["audience"] == "user"


def test_signal_severity_normalization():
    assert normalize_signal_severity("ERROR") == "error"
    assert normalize_signal_severity("unknown") == "info"


def test_decision_mailbox_record_stores_rationale_without_hidden_cot():
    record = DecisionMailboxRecord(
        decision_id="decision-1",
        run_id="run-1",
        status="pending",
        packet={"action": "generate_videos"},
        decision_rationale="Shot 1 has selected_image and is missing selected_video.",
        thinking_artifacts=[
            {"type": "planner_summary", "model": "deepseek-reasoner", "confidence": 0.82}
        ],
    )

    payload = record.as_dict()

    assert payload["decision_rationale"] == "Shot 1 has selected_image and is missing selected_video."
    assert payload["thinking_artifacts"][0]["type"] == "planner_summary"
    assert "chain_of_thought" not in payload
    assert "reasoning_trace" not in payload


def test_runtime_requirement_blocks_missing_provider_capability():
    context = {
        "runtime_features": [
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        ],
        "provider_capabilities": ["seedream_text_to_image"],
        "capability_versions": {"generate_videos": "2026-05-27.v1"},
    }

    with pytest.raises(CapabilityViolation, match="provider capability"):
        ensure_runtime_requirements("generate_videos", context)


def test_runtime_requirement_allows_seedance_video_capability():
    context = {
        "runtime_features": [
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        ],
        "provider_capabilities": ["seedance_image_to_video"],
        "capability_versions": {"generate_videos": "2026-05-27.v1"},
    }

    ensure_runtime_requirements("generate_videos", context)


def test_expected_artifacts_for_video_generation_include_required_outputs():
    artifacts = expected_artifacts_for_action("generate_videos")

    assert ExpectedArtifact(
        artifact_type="selected_video",
        write_target={"table": "shot_rows", "field": "selected_video"},
        required=True,
        source="db_writeback",
    ) in artifacts
    assert any(item.artifact_type == "thumbnail" and item.required is False for item in artifacts)


def test_safety_gate_blocks_dangerous_action():
    with pytest.raises(SafetyReviewRequired, match="delete_project"):
        ensure_safety_gate({"action": "delete_project", "risk": {"score": 0.2}})


def test_safety_gate_blocks_high_risk_packet():
    with pytest.raises(SafetyReviewRequired, match="high risk"):
        ensure_safety_gate({"action": "generate_videos", "risk": {"score": 0.86}})


def test_safety_constants_are_explicit():
    assert "delete_project" in DANGEROUS_ACTIONS
    assert RISK_THRESHOLDS["high"] == 0.8
    assert "generate_videos" in CAPABILITY_REQUIREMENTS
    assert "generate_videos" in ARTIFACT_REQUIREMENTS
    assert ArtifactRef(artifact_type="video", ref="asset-1").required is True
