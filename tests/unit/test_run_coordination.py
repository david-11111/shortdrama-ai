import pytest

from app.services import run_coordination
from app.services.run_coordination import (
    DecisionTickResult,
    UnifiedRunFacts,
    evaluate_decision_tick,
    load_run_facts_from_snapshot,
    observe_task_terminal_decision_tick,
)


def facts(*, shots=None, tasks=None, production_run=None, run=None):
    return UnifiedRunFacts(
        run=run or {"run_id": "run-1", "project_id": "project-1", "goal": "make a short drama"},
        shots=shots or [],
        tasks=tasks or [],
        production_run=production_run or {},
        source="unit_test",
    )


def test_empty_run_executes_story_plan():
    decision = evaluate_decision_tick(facts())

    assert decision.status == "execute"
    assert decision.action == "generate_story_plan"
    assert decision.stage_id == "generate_story_plan"
    assert decision.allowed is True
    assert decision.evidence["shot_count"] == 0
    assert "Generate script" in decision.success_criteria[0]


def test_shots_without_images_execute_keyframes():
    decision = evaluate_decision_tick(
        facts(shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "", "selected_video": ""}])
    )

    assert decision.status == "execute"
    assert decision.action == "generate_keyframes"
    assert decision.stage_id == "generate_keyframes"
    assert decision.allowed is True
    assert decision.evidence["shot_count"] == 1


def test_execute_decision_packet_contains_authoritative_dispatch_fields():
    decision = evaluate_decision_tick(
        facts(shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "", "selected_video": ""}])
    )

    assert decision.packet_version == "main_run_chain_phase1"
    assert decision.selected_lane == "c_lane_production"
    assert decision.dispatchable is True
    assert decision.allowed_writes == ["tasks", "shot_rows", "agent_events", "agent_runs"]
    assert decision.mission["action"] == "generate_keyframes"
    assert decision.mission["lane"] == "c_lane_production"
    assert decision.mission["write_scope"] == ["tasks", "shot_rows", "agent_events", "agent_runs"]
    assert decision.budget["unit"] == "image_gen"
    assert decision.budget["target_count"] == 1
    assert decision.risk["level"] == "medium"
    assert decision.failure_policy["fallback_action"] == ""
    assert decision.evidence_refs[0]["kind"] == "shot_rows"


def test_selected_images_execute_videos():
    decision = evaluate_decision_tick(
        facts(shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "image.png", "selected_video": ""}])
    )

    assert decision.status == "execute"
    assert decision.action == "generate_videos"
    assert decision.stage_id == "generate_videos"
    assert decision.allowed is True
    assert decision.evidence["selected_image_count"] == 1


def test_selected_videos_execute_final_edit():
    decision = evaluate_decision_tick(
        facts(shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "image.png", "selected_video": "video.mp4"}])
    )

    assert decision.status == "execute"
    assert decision.action == "plan_final_edit"
    assert decision.stage_id == "final_cut"
    assert decision.allowed is True
    assert decision.evidence["selected_video_count"] == 1
    assert decision.candidate_actions[0]["action"] == "plan_final_edit"
    assert all(candidate["action"] != "audio_subtitles" for candidate in decision.candidate_actions)


def test_active_tasks_wait_instead_of_dispatching_more_work():
    decision = evaluate_decision_tick(
        facts(
            shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "", "selected_video": ""}],
            tasks=[{"task_id": "task-1", "task_type": "image_gen", "status": "running"}],
        )
    )

    assert decision.status == "wait"
    assert decision.action == "wait_for_tasks"
    assert decision.active_task_count == 1
    assert decision.allowed is False
    assert decision.reason == "Active production tasks are still running."


def test_wait_decision_packet_is_not_dispatchable():
    decision = evaluate_decision_tick(
        facts(
            shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "", "selected_video": ""}],
            tasks=[{"task_id": "task-1", "task_type": "image_gen", "status": "running"}],
        )
    )

    assert decision.packet_version == "main_run_chain_phase1"
    assert decision.selected_lane == "main_chain"
    assert decision.dispatchable is False
    assert decision.mission == {}
    assert decision.failure_policy["fallback_action"] == ""
    assert decision.budget["target_count"] == 0


def test_failed_keyframe_task_routes_to_recovery():
    decision = evaluate_decision_tick(
        facts(
            shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "", "selected_video": ""}],
            tasks=[{"task_id": "task-1", "task_type": "image_gen", "status": "failed", "error_message": "provider failed"}],
        )
    )

    assert decision.status == "recover"
    assert decision.action == "generate_keyframes"
    assert decision.failed_task_count == 1
    assert decision.allowed is False
    assert decision.fallback_action == "fallback_reasoning"


def test_provider_waiting_video_backpressure_waits_instead_of_recovery():
    decision = evaluate_decision_tick(
        facts(
            shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "image.png", "selected_video": ""}],
            tasks=[
                {
                    "task_id": "task-1",
                    "task_type": "video_gen",
                    "status": "failed",
                    "error_message": "provider returned 429 rate limit",
                }
            ],
            production_run={"status": "provider_waiting"},
        )
    )

    assert decision.status == "wait"
    assert decision.action == "wait_for_provider"
    assert decision.allowed is False
    assert decision.failed_task_count == 0


def test_final_video_marks_run_complete():
    decision = evaluate_decision_tick(
        facts(
            shots=[{"shot_index": 1, "prompt": "shot 1", "selected_image": "image.png", "selected_video": "video.mp4"}],
            production_run={"status": "completed", "final_video_url": "https://cdn.test/final.mp4"},
        )
    )

    assert decision.status == "complete"
    assert decision.action == "writeback_review"
    assert decision.allowed is True
    assert decision.evidence["final_video_url"] == "https://cdn.test/final.mp4"


def test_final_video_without_completed_policy_does_not_mark_complete():
    decision = evaluate_decision_tick(
        facts(production_run={"status": "completed", "final_video_url": "https://cdn.test/final.mp4"})
    )

    assert decision.status == "execute"
    assert decision.action == "generate_story_plan"


@pytest.mark.asyncio
async def test_load_run_facts_prefers_output_shots_and_effective_tasks(monkeypatch):
    async def fake_snapshot(db, *, run_id, user_id):
        return {
            "run": {"run_id": run_id, "project_id": "project-1", "goal": "make a short drama", "status": "running"},
            "ledger": {
                "shots": [{"shot_index": 1, "prompt": "old", "selected_image": "", "selected_video": ""}],
            },
            "outputs": {
                "shots": [{"shot_index": 1, "prompt": "new", "selected_image": "image.png", "selected_video": ""}],
                "summary": {"final_video_url": ""},
            },
            "tasks": [
                {
                    "task_id": "task-stale",
                    "task_type": "image_gen",
                    "status": "failed",
                    "payload": {"shot_index": 1},
                }
            ],
        }

    monkeypatch.setattr(run_coordination, "get_agent_run_snapshot", fake_snapshot)

    loaded = await load_run_facts_from_snapshot(object(), run_id="run-1", user_id=7)

    assert loaded is not None
    assert loaded.shots[0]["prompt"] == "new"
    assert loaded.tasks == []


@pytest.mark.asyncio
async def test_load_run_facts_builds_production_facts_from_real_snapshot_outputs(monkeypatch):
    async def fake_snapshot(db, *, run_id, user_id):
        return {
            "run": {
                "run_id": run_id,
                "project_id": "project-1",
                "goal": "make a short drama",
                "status": "completed",
                "current_phase": "writeback",
            },
            "outputs": {
                "shots": [
                    {
                        "shot_index": 1,
                        "prompt": "shot 1",
                        "selected_image": "image.png",
                        "selected_video": "video.mp4",
                    }
                ],
                "summary": {"final_video_url": "https://cdn.test/final.mp4"},
            },
            "state_machine": {"stage": "writeback_review"},
            "tasks": [],
        }

    monkeypatch.setattr(run_coordination, "get_agent_run_snapshot", fake_snapshot)

    loaded = await load_run_facts_from_snapshot(object(), run_id="run-1", user_id=7)

    assert loaded is not None
    assert loaded.production_run["status"] == "completed"
    assert loaded.production_run["final_video_url"] == "https://cdn.test/final.mp4"
    assert loaded.production_run["current_stage"] == "writeback"
    assert evaluate_decision_tick(loaded).status == "complete"


@pytest.mark.asyncio
async def test_load_run_facts_provider_waiting_from_run_current_phase(monkeypatch):
    async def fake_snapshot(db, *, run_id, user_id):
        return {
            "run": {
                "run_id": run_id,
                "project_id": "project-1",
                "goal": "make a short drama",
                "status": "running",
                "current_phase": "provider_waiting",
            },
            "outputs": {
                "shots": [{"shot_index": 1, "prompt": "shot 1", "selected_image": "image.png", "selected_video": ""}],
                "summary": {"final_video_url": ""},
            },
            "state_machine": {"stage": "generate_videos"},
            "tasks": [
                {
                    "task_id": "task-1",
                    "task_type": "video_gen",
                    "status": "failed",
                    "error_message": "provider saturated with backpressure",
                }
            ],
        }

    monkeypatch.setattr(run_coordination, "get_agent_run_snapshot", fake_snapshot)

    loaded = await load_run_facts_from_snapshot(object(), run_id="run-1", user_id=7)

    assert loaded is not None
    assert loaded.production_run["status"] == "provider_waiting"
    assert evaluate_decision_tick(loaded).action == "wait_for_provider"


@pytest.mark.asyncio
async def test_observer_invalid_uuid_returns_none_without_opening_session(monkeypatch):
    def fail_session_local():
        raise AssertionError("session should not be opened for invalid UUID")

    monkeypatch.setattr(run_coordination, "AsyncSessionLocal", fail_session_local)

    assert await observe_task_terminal_decision_tick("not-a-uuid") is None


@pytest.mark.asyncio
async def test_observer_existing_decision_returns_stored_decision_without_publish(monkeypatch):
    stored = {"status": "wait", "action": "wait_for_tasks"}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_context(session, task_id):
        return {"run_id": "11111111-1111-1111-1111-111111111111", "project_id": "project-1", "user_id": 7}

    async def fake_existing(session, *, task_id):
        return stored

    async def fail_load(*args, **kwargs):
        raise AssertionError("facts should not be loaded when a decision already exists")

    async def fail_publish(*args, **kwargs):
        raise AssertionError("publish_agent_event should not be called for an existing decision")

    monkeypatch.setattr(run_coordination, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(run_coordination, "_task_run_context", fake_context)
    monkeypatch.setattr(run_coordination, "_existing_decision_event", fake_existing)
    monkeypatch.setattr(run_coordination, "load_run_facts_from_snapshot", fail_load)
    monkeypatch.setattr(run_coordination, "publish_agent_event", fail_publish)

    result = await observe_task_terminal_decision_tick("22222222-2222-2222-2222-222222222222")

    assert result == stored


@pytest.mark.asyncio
async def test_observer_new_decision_publishes_state_machine_debug_event(monkeypatch):
    published = {}
    commits = []
    decision = DecisionTickResult(
        packet_version="main_run_chain_phase1",
        status="execute",
        action="generate_story_plan",
        stage_id="generate_story_plan",
        selected_lane="a_lane_project_brain",
        dispatchable=True,
        allowed=True,
        reason="ready",
        missing=[],
        fallback_action="",
        active_task_count=0,
        failed_task_count=0,
        allowed_writes=["project_workspace", "shot_rows", "agent_events", "agent_runs"],
        evidence={},
        evidence_refs=[],
        candidate_actions=[],
        success_criteria=[],
        budget={"unit": "", "target_count": 0, "estimated_max_credits": None, "source": "test"},
        risk={"level": "low", "failed_task_count": 0, "requires_human": False},
        failure_policy={"fallback_action": "", "retryable": True, "require_human_confirmation": False},
        mission={"mission_id": "run-1:generate_story_plan", "lane": "a_lane_project_brain", "action": "generate_story_plan", "write_scope": ["project_workspace"], "idempotency_key": "run-1:generate_story_plan"},
    )

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            commits.append(True)

    async def fake_context(session, task_id):
        return {"run_id": "11111111-1111-1111-1111-111111111111", "project_id": "project-1", "user_id": 7}

    async def fake_existing(session, *, task_id):
        return None

    async def fake_load(session, *, run_id, user_id):
        return facts()

    def fake_evaluate(loaded_facts):
        return decision

    async def fake_publish(session, **kwargs):
        published.update(kwargs)
        return {}

    monkeypatch.setattr(run_coordination, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(run_coordination, "_task_run_context", fake_context)
    monkeypatch.setattr(run_coordination, "_existing_decision_event", fake_existing)
    monkeypatch.setattr(run_coordination, "load_run_facts_from_snapshot", fake_load)
    monkeypatch.setattr(run_coordination, "evaluate_decision_tick", fake_evaluate)
    monkeypatch.setattr(run_coordination, "publish_agent_event", fake_publish)

    result = await observe_task_terminal_decision_tick("22222222-2222-2222-2222-222222222222")

    assert result == decision.as_dict()
    assert published["source"] == "state_machine"
    assert published["event_type"] == "decision"
    assert published["phase"] == "decision_tick"
    assert published["visibility"] == "debug"
    assert published["meta"]["decision_tick"] == decision.as_dict()
    assert commits == [True]
