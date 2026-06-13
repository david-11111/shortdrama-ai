from app.routes.workbench import _resolve_authoritative_dispatch_action
from app.services.run_coordination import DecisionTickResult


def packet(action: str, status: str = "execute") -> DecisionTickResult:
    return DecisionTickResult(
        packet_version="main_run_chain_phase1",
        status=status,
        action=action,
        stage_id=action,
        selected_lane="c_lane_production",
        dispatchable=True,
        allowed=status == "execute",
        reason="unit",
        missing=[],
        fallback_action="",
        active_task_count=0,
        failed_task_count=0,
        allowed_writes=[],
        evidence={},
        evidence_refs=[],
        candidate_actions=[],
        success_criteria=[],
        budget={},
        risk={},
        failure_policy={},
        mission={},
    )


def test_execute_packet_takes_authority_over_stale_requested_action():
    action, compatible = _resolve_authoritative_dispatch_action(
        "plan_visual_assets",
        packet("generate_keyframes"),
    )

    assert compatible is True
    assert action == "generate_keyframes"


def test_review_to_generate_compatibility_keeps_requested_generation_action():
    action, compatible = _resolve_authoritative_dispatch_action(
        "generate_keyframes",
        packet("review_keyframes"),
    )

    assert compatible is True
    assert action == "generate_keyframes"
