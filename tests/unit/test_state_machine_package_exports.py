from __future__ import annotations


def test_state_machine_package_exports_policy_lookup() -> None:
    from app.services.state_machine import POLICY_BY_STAGE_ID, evaluate_action_gate

    assert POLICY_BY_STAGE_ID
    assert callable(evaluate_action_gate)
