import pytest

from app.services.run_coordination import DecisionTickResult


def packet(status="execute", action="generate_keyframes", dispatchable=True, allowed=True):
    mission = {
        "mission_id": f"run-1:{action}",
        "lane": "c_lane_production",
        "action": action,
        "write_scope": ["tasks", "shot_rows", "agent_events", "agent_runs"],
        "idempotency_key": f"run-1:{action}",
    } if dispatchable else {}
    return DecisionTickResult(
        packet_version="main_run_chain_phase1",
        status=status,
        action=action,
        stage_id=action,
        selected_lane="c_lane_production" if dispatchable else "main_chain",
        dispatchable=dispatchable,
        allowed=allowed,
        reason="ready",
        missing=[],
        fallback_action="",
        active_task_count=0,
        failed_task_count=0,
        allowed_writes=["tasks", "shot_rows", "agent_events", "agent_runs"],
        evidence={"project_id": "project-1", "run_id": "run-1"},
        evidence_refs=[],
        candidate_actions=[],
        success_criteria=[],
        budget={"target_count": 1, "estimated_max_credits": 0, "unit": "image_gen"},
        risk={"level": "medium", "failed_task_count": 0, "requires_human": False},
        failure_policy={"fallback_action": "", "retryable": True, "require_human_confirmation": False},
        mission=mission,
    )


@pytest.mark.asyncio
async def test_execute_decision_dispatches_through_gateway(monkeypatch):
    from app.services import main_chain_controller

    observed = {"called": False, "mailbox": None}

    async def fake_dispatch(db, *, packet, context, handlers):
        observed["called"] = True
        assert "generate_keyframes" in handlers
        return {"run_id": context.run_id, "queued_count": 1}

    async def fake_submit(_db, **kwargs):
        observed["mailbox"] = kwargs
        return "pending-event"

    monkeypatch.setattr(main_chain_controller, "dispatch_authoritative_packet", fake_dispatch)
    monkeypatch.setattr(main_chain_controller.decision_mailbox, "submit_decision", fake_submit)

    async def handler():
        return {"queued_count": 1}

    result = await main_chain_controller.apply_decision_packet(
        object(),
        packet=packet(),
        context=main_chain_controller.MainChainContext(
            project_id="project-1",
            user_id=7,
            user_tier="pro",
            run_id="run-1",
            run_mode="autopilot",
        ),
        handlers={"generate_keyframes": handler},
    )

    assert observed["called"] is True
    assert observed["mailbox"]["packet"]["action"] == "generate_keyframes"
    assert observed["mailbox"]["decision_rationale"] == "ready"
    assert observed["mailbox"]["thinking_artifacts"][0]["type"] == "decision_evidence"
    assert result.status == "dispatched"
    assert result.dispatched is True


@pytest.mark.asyncio
async def test_execute_video_decision_passes_runtime_capabilities_to_gateway(monkeypatch):
    from app.services import main_chain_controller

    observed = {"context": None}

    async def fake_dispatch(db, *, packet, context, handlers):
        observed["context"] = context
        return {"run_id": context.run_id, "queued_count": 1}

    async def fake_submit(*args, **kwargs):
        return "pending-event"

    monkeypatch.setattr(main_chain_controller, "dispatch_authoritative_packet", fake_dispatch)
    monkeypatch.setattr(main_chain_controller.decision_mailbox, "submit_decision", fake_submit)

    async def handler():
        return {"queued_count": 1}

    result = await main_chain_controller.apply_decision_packet(
        object(),
        packet=packet(action="generate_videos"),
        context=main_chain_controller.MainChainContext(
            project_id="project-1",
            user_id=7,
            user_tier="pro",
            run_id="run-1",
            run_mode="autopilot",
        ),
        handlers={"generate_videos": handler},
    )

    assert result.status == "dispatched"
    assert "video_generation" in observed["context"].runtime_features
    assert "ltx23_image_to_video" in observed["context"].provider_capabilities


@pytest.mark.asyncio
async def test_wait_decision_does_not_dispatch(monkeypatch):
    from app.services import main_chain_controller

    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("wait decisions must not dispatch")

    async def fake_update(db, **kwargs):
        assert kwargs["status"] == "running"
        assert kwargs["current_phase"] == "wait_for_tasks"

    async def fake_publish(*args, **kwargs):
        return {"id": "event-1"}

    async def fake_feedback(*args, **kwargs):
        return {"id": "feedback-1"}

    monkeypatch.setattr(main_chain_controller, "dispatch_authoritative_packet", fail_dispatch)
    monkeypatch.setattr(main_chain_controller, "update_agent_run", fake_update)
    monkeypatch.setattr(main_chain_controller, "publish_agent_event", fake_publish)
    monkeypatch.setattr(main_chain_controller.main_chain_feedback, "publish_runtime_feedback", fake_feedback)

    result = await main_chain_controller.apply_decision_packet(
        object(),
        packet=packet(status="wait", action="wait_for_tasks", dispatchable=False, allowed=False),
        context=main_chain_controller.MainChainContext("project-1", 7, "pro", "run-1", "autopilot"),
        handlers={},
    )

    assert result.status == "waiting"
    assert result.dispatched is False


@pytest.mark.asyncio
async def test_complete_decision_marks_run_completed(monkeypatch):
    from app.services import main_chain_controller

    observed = {}

    async def fake_update(db, **kwargs):
        observed.update(kwargs)

    async def fake_publish(*args, **kwargs):
        return {"id": "event-1"}

    async def fake_feedback(*args, **kwargs):
        return {"id": "feedback-1"}

    monkeypatch.setattr(main_chain_controller, "update_agent_run", fake_update)
    monkeypatch.setattr(main_chain_controller, "publish_agent_event", fake_publish)
    monkeypatch.setattr(main_chain_controller.main_chain_feedback, "publish_runtime_feedback", fake_feedback)

    result = await main_chain_controller.apply_decision_packet(
        object(),
        packet=packet(status="complete", action="writeback_review", dispatchable=False),
        context=main_chain_controller.MainChainContext("project-1", 7, "pro", "run-1", "autopilot"),
        handlers={},
    )

    assert observed["status"] == "completed"
    assert observed["current_phase"] == "writeback_review"
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_wait_decision_publishes_runtime_feedback(monkeypatch):
    from app.services import main_chain_controller

    observed = {"feedback": None}

    async def fake_update(*args, **kwargs):
        return None

    async def fake_publish(*args, **kwargs):
        return {"id": "event-1"}

    async def fake_feedback(_db, **kwargs):
        observed["feedback"] = kwargs["feedback"].as_dict()
        return {"id": "feedback-1"}

    monkeypatch.setattr(main_chain_controller, "update_agent_run", fake_update)
    monkeypatch.setattr(main_chain_controller, "publish_agent_event", fake_publish)
    monkeypatch.setattr(main_chain_controller.main_chain_feedback, "publish_runtime_feedback", fake_feedback)

    await main_chain_controller.apply_decision_packet(
        object(),
        packet=packet(status="wait", action="wait_for_tasks", dispatchable=False, allowed=False),
        context=main_chain_controller.MainChainContext("project-1", 7, "pro", "run-1", "autopilot"),
        handlers={},
    )

    assert observed["feedback"]["status"] == "waiting"
    assert "wait_for_tasks" in observed["feedback"]["summary"]


@pytest.mark.asyncio
async def test_dangerous_action_is_blocked_before_dispatch(monkeypatch):
    from app.services import main_chain_controller

    observed = {"dispatch": False, "feedback": None}

    async def fake_dispatch(*args, **kwargs):
        observed["dispatch"] = True
        return {"queued_count": 1}

    async def fake_submit(*args, **kwargs):
        raise AssertionError("safety-blocked packets must not enter mailbox pending state")

    async def fake_update(*args, **kwargs):
        return None

    async def fake_publish(*args, **kwargs):
        return {"id": "event-1"}

    async def fake_feedback(_db, **kwargs):
        observed["feedback"] = kwargs["feedback"].as_dict()
        return {"id": "feedback-1"}

    monkeypatch.setattr(main_chain_controller, "dispatch_authoritative_packet", fake_dispatch)
    monkeypatch.setattr(main_chain_controller.decision_mailbox, "submit_decision", fake_submit)
    monkeypatch.setattr(main_chain_controller, "update_agent_run", fake_update)
    monkeypatch.setattr(main_chain_controller, "publish_agent_event", fake_publish)
    monkeypatch.setattr(main_chain_controller.main_chain_feedback, "publish_runtime_feedback", fake_feedback)

    result = await main_chain_controller.apply_decision_packet(
        object(),
        packet=packet(action="delete_project"),
        context=main_chain_controller.MainChainContext("project-1", 7, "pro", "run-1", "autopilot"),
        handlers={"delete_project": fake_dispatch},
    )

    assert observed["dispatch"] is False
    assert result.status == "blocked"
    assert observed["feedback"]["status"] == "blocked"
    assert observed["feedback"]["requires_user"] is True
    assert observed["feedback"]["call_to_action"]["type"] == "dangerous_action_review"


@pytest.mark.asyncio
async def test_high_risk_packet_is_blocked_before_dispatch(monkeypatch):
    from dataclasses import replace

    from app.services import main_chain_controller

    observed = {"dispatch": False, "feedback": None}

    async def fake_dispatch(*args, **kwargs):
        observed["dispatch"] = True
        return {"queued_count": 1}

    async def fake_submit(*args, **kwargs):
        raise AssertionError("safety-blocked packets must not enter mailbox pending state")

    async def fake_update(*args, **kwargs):
        return None

    async def fake_publish(*args, **kwargs):
        return {"id": "event-1"}

    async def fake_feedback(_db, **kwargs):
        observed["feedback"] = kwargs["feedback"].as_dict()
        return {"id": "feedback-1"}

    monkeypatch.setattr(main_chain_controller, "dispatch_authoritative_packet", fake_dispatch)
    monkeypatch.setattr(main_chain_controller.decision_mailbox, "submit_decision", fake_submit)
    monkeypatch.setattr(main_chain_controller, "update_agent_run", fake_update)
    monkeypatch.setattr(main_chain_controller, "publish_agent_event", fake_publish)
    monkeypatch.setattr(main_chain_controller.main_chain_feedback, "publish_runtime_feedback", fake_feedback)

    risky_packet = replace(packet(action="generate_videos"), risk={"score": 0.86, "level": "high"})

    result = await main_chain_controller.apply_decision_packet(
        object(),
        packet=risky_packet,
        context=main_chain_controller.MainChainContext("project-1", 7, "pro", "run-1", "autopilot"),
        handlers={"generate_videos": fake_dispatch},
    )

    assert observed["dispatch"] is False
    assert result.status == "blocked"
    assert "review" in observed["feedback"]["next_step"].lower()


def test_handler_registry_exposes_production_actions():
    from app.services.main_chain_handlers import build_main_chain_handlers

    handlers = build_main_chain_handlers(
        object(),
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        run_id="run-1",
        run_mode="autopilot",
    )

    assert "generate_keyframes" in handlers
    assert "generate_videos" in handlers
    assert "plan_final_edit" in handlers
