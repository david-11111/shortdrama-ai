from app.services.agent_runtime_contract import decide_runtime_action, public_capability


def _active(count: int = 0) -> dict:
    return {"count": count, "task_ids": ["task-a"] if count else [], "statuses": ["running"] if count else [], "items": []}


def test_runtime_contract_inspects_diagnostic_before_execution():
    decision = decide_runtime_action(
        routing={"intent_type": "ui_diagnostic", "resolved_action": "status_query"},
        active_tasks=_active(),
        current_status="dispatching",
    )

    assert decision.kind == "inspect"
    assert decision.capability == "status_query"
    assert decision.allowed is True


def test_runtime_contract_blocks_execute_when_ceiling_is_inspect_only():
    decision = decide_runtime_action(
        routing={"resolved_action": "generate_keyframes", "action_ceiling": "inspect_only", "utterance_type": "question"},
        active_tasks=_active(),
        current_status="dispatching",
    )

    assert decision.kind == "inspect"
    assert decision.action == "status_query"
    assert decision.reason == "inspect_only_ceiling"


def test_runtime_contract_asks_confirm_without_pending_action():
    decision = decide_runtime_action(
        routing={"resolved_action": "generate_videos", "action_ceiling": "pending_confirm", "utterance_type": "confirm"},
        active_tasks=_active(),
        current_status="dispatching",
    )

    assert decision.kind == "ask"
    assert decision.reason == "pending_confirm_without_pending_action"


def test_runtime_contract_asks_when_planner_needs_human_details():
    decision = decide_runtime_action(
        routing={"planner": {"dispatch_ready": False, "reply": "请指定镜头。", "reason": "missing target"}},
        active_tasks=_active(),
        current_status="dispatching",
    )

    assert decision.kind == "ask"
    assert decision.needs_human is True
    assert decision.user_message == "请指定镜头。"


def test_runtime_contract_defers_write_action_while_busy():
    decision = decide_runtime_action(
        routing={"resolved_action": "generate_videos"},
        active_tasks=_active(1),
        current_status="dispatching",
    )

    assert decision.kind == "defer"
    assert decision.action == "generate_videos"
    assert "任务正在执行" in decision.user_message


def test_runtime_contract_rejects_unregistered_action():
    decision = decide_runtime_action(
        routing={"resolved_action": "delete_everything"},
        active_tasks=_active(),
        current_status="dispatching",
    )

    assert decision.kind == "reject"
    assert decision.allowed is False
    assert decision.reason == "capability_not_registered"


def test_runtime_contract_executes_registered_idle_action():
    decision = decide_runtime_action(
        routing={"resolved_action": "generate_keyframes"},
        active_tasks=_active(),
        current_status="dispatching",
    )

    assert decision.kind == "execute"
    assert decision.capability == "generate_keyframes"


def test_public_capability_exposes_policy_not_internal_implementation():
    capability = public_capability("generate_videos")

    assert capability["risk_level"] == "expensive_write"
    assert capability["auto_execute_policy"] == "idle_auto_execute_with_budget_gate"
    assert "tools" not in capability
