from __future__ import annotations

import pytest

from app.services import run_dispatch_gateway
from app.services.run_coordination import DecisionTickResult
from app.services.run_dispatch_gateway import DispatchGatewayContext


def packet(*, status="execute", action="generate_keyframes", lane="c_lane_production", dispatchable=True):
    return DecisionTickResult(
        packet_version="main_run_chain_phase1",
        status=status,
        action=action,
        stage_id=action,
        selected_lane=lane,
        dispatchable=dispatchable,
        allowed=status == "execute",
        reason="ready",
        missing=[],
        fallback_action="request_human_confirmation" if status != "execute" else "",
        active_task_count=0,
        failed_task_count=0,
        allowed_writes=["tasks", "shot_rows", "agent_events", "agent_runs"],
        evidence={"project_id": "project-1", "run_id": "run-1"},
        evidence_refs=[{"kind": "shot_rows", "project_id": "project-1"}],
        candidate_actions=[],
        success_criteria=[],
        budget={"estimated_max_credits": 80, "target_count": 1, "unit": "image_gen", "source": "compat"},
        risk={"level": "medium", "failed_task_count": 0, "requires_human": False},
        failure_policy={"fallback_action": "", "retryable": True, "require_human_confirmation": False},
        mission={
            "mission_id": f"run-1:{action}",
            "lane": lane,
            "action": action,
            "write_scope": ["tasks", "shot_rows", "agent_events", "agent_runs"],
            "idempotency_key": f"run-1:{action}",
        }
        if dispatchable
        else {},
    )


@pytest.mark.asyncio
async def test_dispatch_gateway_updates_run_publishes_event_and_calls_handler(monkeypatch):
    observed = {"updated": None, "published": None, "handled": False, "completed": None, "feedback": None}

    async def fake_update(_db, **kwargs):
        observed["updated"] = kwargs

    async def fake_publish(_db, **kwargs):
        observed["published"] = kwargs
        return {"id": "event-1"}

    async def handler():
        observed["handled"] = True
        return {"queued_count": 2}

    async def fake_complete(_db, **kwargs):
        observed["completed"] = kwargs
        return "completed-event"

    async def fake_feedback(_db, **kwargs):
        observed["feedback"] = kwargs["feedback"].as_dict()
        return {"id": "feedback-1"}

    monkeypatch.setattr(run_dispatch_gateway, "update_agent_run", fake_update)
    monkeypatch.setattr(run_dispatch_gateway, "publish_agent_event", fake_publish)
    monkeypatch.setattr(run_dispatch_gateway.decision_mailbox, "complete_decision", fake_complete)
    monkeypatch.setattr(run_dispatch_gateway.main_chain_feedback, "publish_runtime_feedback", fake_feedback)

    result = await run_dispatch_gateway.dispatch_authoritative_packet(
        object(),
        packet=packet(),
        context=DispatchGatewayContext(
            project_id="project-1",
            user_id=7,
            user_tier="pro",
            run_id="run-1",
            run_mode="step",
        ),
        handlers={"generate_keyframes": handler},
    )

    assert observed["handled"] is True
    assert observed["updated"]["current_phase"] == "dispatch_gateway"
    assert observed["published"]["source"] == "dispatch_gateway"
    assert observed["published"]["meta"]["decision_packet"]["action"] == "generate_keyframes"
    assert result["queued_count"] == 2
    assert result["run_id"] == "run-1"
    assert observed["completed"]["result_ref"]["queued_count"] == 2
    assert observed["feedback"]["status"] == "executing"
    assert "generate_keyframes" in observed["feedback"]["summary"]


@pytest.mark.asyncio
async def test_dispatch_gateway_rejects_non_dispatchable_packets(monkeypatch):
    async def fail_handler():
        raise AssertionError("handler should not run")

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(run_dispatch_gateway, "update_agent_run", noop)
    monkeypatch.setattr(run_dispatch_gateway, "publish_agent_event", noop)

    with pytest.raises(ValueError, match="not dispatchable"):
        await run_dispatch_gateway.dispatch_authoritative_packet(
            object(),
            packet=packet(status="wait", action="wait_for_tasks", lane="main_chain", dispatchable=False),
            context=DispatchGatewayContext(
                project_id="project-1",
                user_id=7,
                user_tier="pro",
                run_id="run-1",
                run_mode="step",
            ),
            handlers={"wait_for_tasks": fail_handler},
        )


@pytest.mark.asyncio
async def test_dispatch_gateway_rejects_b_lane_provider_execution(monkeypatch):
    observed = {"rejected": None}

    async def fail_handler():
        raise AssertionError("handler should not run")

    async def fake_reject(_db, **kwargs):
        observed["rejected"] = kwargs
        return "rejected-event"

    monkeypatch.setattr(run_dispatch_gateway.decision_mailbox, "mark_decision_rejected", fake_reject)

    with pytest.raises(ValueError, match="b_lane_agent_runs cannot execute"):
        await run_dispatch_gateway.dispatch_authoritative_packet(
            object(),
            packet=packet(action="generate_videos", lane="b_lane_agent_runs"),
            context=DispatchGatewayContext(
                project_id="project-1",
                user_id=7,
                user_tier="pro",
                run_id="run-1",
                run_mode="step",
            ),
            handlers={"generate_videos": fail_handler},
        )

    assert observed["rejected"]["decision_id"] == "run-1:generate_videos"


@pytest.mark.asyncio
async def test_dispatch_gateway_rejects_missing_provider_capability(monkeypatch):
    observed = {"rejected": None}

    async def fail_handler():
        raise AssertionError("handler should not run")

    async def fake_reject(_db, **kwargs):
        observed["rejected"] = kwargs
        return "rejected-event"

    monkeypatch.setattr(run_dispatch_gateway.decision_mailbox, "mark_decision_rejected", fake_reject)

    context = DispatchGatewayContext(
        project_id="project-1",
        user_id=7,
        user_tier="pro",
        run_id="run-1",
        run_mode="step",
        runtime_features=[
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        ],
        provider_capabilities=["seedream_text_to_image"],
        capability_versions={"generate_videos": "2026-05-27.v1"},
    )

    with pytest.raises(ValueError, match="provider capability"):
        await run_dispatch_gateway.dispatch_authoritative_packet(
            object(),
            packet=packet(action="generate_videos", lane="c_lane_production"),
            context=context,
            handlers={"generate_videos": fail_handler},
        )

    assert "provider capability" in observed["rejected"]["reason"]


@pytest.mark.asyncio
async def test_dispatch_gateway_allows_seedance_video_capability(monkeypatch):
    observed = {"handler": False}

    async def fake_update(*args, **kwargs):
        return None

    async def fake_publish(*args, **kwargs):
        return {"id": "event-1"}

    async def fake_complete(*args, **kwargs):
        return "completed-event"

    async def handler():
        observed["handler"] = True
        return {"queued_count": 1}

    monkeypatch.setattr(run_dispatch_gateway, "update_agent_run", fake_update)
    monkeypatch.setattr(run_dispatch_gateway, "publish_agent_event", fake_publish)
    monkeypatch.setattr(run_dispatch_gateway.decision_mailbox, "complete_decision", fake_complete)
    monkeypatch.setattr(run_dispatch_gateway.main_chain_feedback, "publish_runtime_feedback", fake_publish)

    context = DispatchGatewayContext(
        "project-1",
        7,
        "pro",
        "run-1",
        "step",
        runtime_features=[
            "video_generation",
            "provider_status_observation",
            "selected_video_writeback",
        ],
        provider_capabilities=["seedance_image_to_video"],
        capability_versions={"generate_videos": "2026-05-27.v1"},
    )

    await run_dispatch_gateway.dispatch_authoritative_packet(
        object(),
        packet=packet(action="generate_videos", lane="c_lane_production"),
        context=context,
        handlers={"generate_videos": handler},
    )

    assert observed["handler"] is True
