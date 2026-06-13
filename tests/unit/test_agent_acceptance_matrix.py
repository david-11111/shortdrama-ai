import json
import sys
import types
from pathlib import Path
from unittest.mock import ANY, AsyncMock

import pytest

from app.services import agent_pending_instructions
from app.services.agent_run_snapshot import _build_actions, _build_outputs, _build_stream, _event
from app.tasks import _shared


ROOT = Path(__file__).resolve().parents[2]


class _Rows:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class _Result:
    def __init__(self, row=None, scalar=None):
        self.row = row
        self.scalar = scalar

    def mappings(self):
        return _Rows(self.row)

    def scalar_one_or_none(self):
        return self.scalar


class _PendingDb:
    def __init__(self, meta):
        self.meta = meta
        self.updates = []
        self.commits = 0

    async def execute(self, statement, params):
        sql = str(statement)
        if "SELECT id::text AS id, meta" in sql:
            return _Result({"id": "event-1", "meta": self.meta})
        if "SELECT meta FROM agent_events" in sql:
            return _Result({"meta": self.meta})
        if "UPDATE agent_events SET meta" in sql:
            decoded = json.loads(params["meta"])
            self.meta = decoded
            self.updates.append(decoded["pending_instruction"]["status"])
            return _Result()
        raise AssertionError(f"unexpected SQL in pending queue test: {sql}")

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_pending_instruction_queue_moves_from_queued_to_dispatching_then_dispatched():
    db = _PendingDb({
        "pending_instruction": {
            "status": "queued",
            "instruction": "redo visual assets",
            "continue_body": {"action": "plan_visual_assets"},
            "routing": {"resolved_action": "plan_visual_assets"},
        }
    })

    claimed = await agent_pending_instructions._claim_next_pending_instruction(db, run_id="run-1", user_id=7)
    await agent_pending_instructions._mark_pending_instruction(
        db,
        event_id=claimed["id"],
        status="dispatched",
        result={"run_id": "run-2", "status": "completed"},
    )

    assert claimed["id"] == "event-1"
    assert db.updates == ["dispatching", "dispatched"]
    assert db.meta["pending_instruction"]["result"]["run_id"] == "run-2"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_pending_instruction_queue_records_failed_dispatch():
    db = _PendingDb({"pending_instruction": {"status": "dispatching", "instruction": "redo video"}})

    await agent_pending_instructions._mark_pending_instruction(
        db,
        event_id="event-1",
        status="failed",
        result={"error": "provider unavailable"},
    )

    assert db.updates == ["failed"]
    assert db.meta["pending_instruction"]["result"] == {"error": "provider unavailable"}


@pytest.mark.asyncio
async def test_task_complete_drains_queued_instruction_after_run_is_idle(monkeypatch):
    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    class _SessionLocal:
        def __call__(self):
            return _Session()

    workbench = types.ModuleType("app.routes.workbench")
    workbench.continue_project_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    monkeypatch.setitem(sys.modules, "app.routes.workbench", workbench)
    monkeypatch.setattr(agent_pending_instructions, "AsyncSessionLocal", _SessionLocal())
    monkeypatch.setattr(
        agent_pending_instructions,
        "_task_context",
        AsyncMock(return_value={"run_id": "run-1", "project_id": "project-1", "user_id": 7}),
    )
    monkeypatch.setattr(agent_pending_instructions, "_has_active_tasks", AsyncMock(return_value=False))
    monkeypatch.setattr(
        agent_pending_instructions,
        "_claim_next_pending_instruction",
        AsyncMock(
            return_value={
                "id": "event-1",
                "meta": {
                    "pending_instruction": {
                        "status": "dispatching",
                        "instruction": "参考图不行",
                        "continue_body": {"action": "plan_visual_assets"},
                        "routing": {"resolved_action": "plan_visual_assets"},
                    }
                },
            }
        ),
    )
    mark = AsyncMock()
    publish = AsyncMock()
    monkeypatch.setattr(agent_pending_instructions, "_mark_pending_instruction", mark)
    monkeypatch.setattr(agent_pending_instructions, "publish_agent_event", publish)

    await agent_pending_instructions.drain_pending_instruction_after_task("task-1")

    workbench.continue_project_brain.assert_awaited_once()
    assert workbench.continue_project_brain.await_args.kwargs["body"] == {"action": "plan_visual_assets"}
    mark.assert_awaited_once_with(ANY, event_id="event-1", status="dispatched", result={"run_id": "run-2", "status": "queued"})
    assert publish.await_args_list[0].kwargs["phase"] == "pending_instruction_dispatch"
    assert publish.await_args_list[1].kwargs["phase"] == "pending_instruction_dispatched"


@pytest.mark.asyncio
async def test_pending_instruction_claim_is_single_winner_under_concurrency():
    class _ConcurrentPendingDb(_PendingDb):
        async def execute(self, statement, params):
            sql = str(statement)
            if "SELECT id::text AS id, meta" in sql:
                pending = self.meta.get("pending_instruction", {})
                if pending.get("status") != "queued":
                    return _Result(None)
                return _Result({"id": "event-1", "meta": self.meta})
            return await super().execute(statement, params)

    db = _ConcurrentPendingDb({"pending_instruction": {"status": "queued", "continue_body": {"action": "plan_visual_assets"}}})

    first = await agent_pending_instructions._claim_next_pending_instruction(db, run_id="run-1", user_id=7)
    second = await agent_pending_instructions._claim_next_pending_instruction(db, run_id="run-1", user_id=7)

    assert first["id"] == "event-1"
    assert second is None
    assert db.updates == ["dispatching"]


@pytest.mark.parametrize(
    ("task_type", "tool", "event_type", "expected_phase", "expected_title"),
    [
        ("director_script", "doubao", "tool_call", "doubao_requesting", "豆包剧本/导演"),
        ("image_gen", "seedream", "tool_result", "seedream_result", "Seedream 出图"),
        ("video_gen", "seedance", "tool_result", "seedance_result", "Seedance 视频"),
        ("video_gen", "kling", "tool_result", "kling_result", "Kling 视频"),
    ],
)
def test_provider_events_are_visible_agent_events(task_type, tool, event_type, expected_phase, expected_title):
    event = _shared._build_task_agent_event(
        "task-1",
        event_type,
        {"tool": tool, "prompt": "shot prompt", "url": "https://cdn.test/out", "progress": 80},
        {"run_id": "run-1", "project_id": "project-1", "user_id": 7, "task_type": task_type},
    )

    assert event["type"] == "execution_event"
    assert event["phase"] == expected_phase
    assert event["status"] in {"running", "done"}
    assert expected_title in event["title"]
    assert event["meta"]["tool"] == tool


def test_recovery_actions_are_enabled_by_failed_or_partial_video_outputs():
    actions = {
        item["id"]: item
        for item in _build_actions(
            run={"status": "failed"},
            nodes=[],
            tasks=[
                {"task_type": "video_gen", "status": "failed"},
                {"task_type": "video_gen", "status": "completed"},
            ],
            production_run=None,
        )
    }

    assert actions["retry_failed"]["enabled"] is True
    assert actions["change_provider"]["enabled"] is True
    assert actions["export_partial"]["enabled"] is True
    assert actions["continue_step"]["enabled"] is True


def test_snapshot_outputs_and_stream_expose_artifacts_without_debug_leak():
    events = [
        _event(
            {
                "id": "event-decision",
                "run_id": "run-1",
                "project_id": "project-1",
                "task_id": None,
                "step_id": None,
                "user_id": 7,
                "source": "deepseek",
                "event_type": "decision",
                "phase": "llm_planner",
                "title": "DeepSeek decision",
                "detail": "Reference image feedback routes to visual assets.",
                "status": "done",
                "progress": 80,
                "meta": {"agent_event": {"actor": "deepseek", "event_kind": "decision", "summary": "DeepSeek chose plan_visual_assets", "reason": "reference image rejected"}},
                "created_at": None,
            }
        ),
        _event(
            {
                "id": "event-debug",
                "run_id": "run-1",
                "project_id": "project-1",
                "task_id": None,
                "step_id": None,
                "user_id": 7,
                "source": "deepseek",
                "event_type": "trace",
                "phase": "llm_planner",
                "title": "Raw planner JSON",
                "detail": "{}",
                "status": "done",
                "progress": 1,
                "meta": {"agent_event": {"visibility": "debug", "summary": "raw planner payload", "debug": {"tokens": 12}}},
                "created_at": None,
            }
        ),
    ]
    outputs = _build_outputs(
        run={"summary": "run summary"},
        events=events,
        tasks=[
            {"task_id": "script-task", "task_type": "director_script", "stage_text": "script", "payload": {}, "result": {"script": "Opening scene text."}},
            {"task_id": "image-task", "task_type": "image_gen", "stage_text": "image", "payload": {"shot_index": 1}, "result": {"image_url": "https://cdn.test/shot1.png"}},
            {"task_id": "video-task", "task_type": "video_gen", "stage_text": "video", "payload": {"shot_index": 1}, "result": {"video_url": "https://cdn.test/shot1.mp4"}},
        ],
        steps=[{"phase": "generate_story_plan", "title": "Storyboard", "decision_summary": "Use a close-up beat.", "output_summary": "Storyboard output."}],
        artifacts=[],
        shots=[
            {
                "shot_index": 1,
                "prompt": "close-up",
                "duration": 4,
                "status": "video_done",
                "selected_image": "https://cdn.test/selected.png",
                "selected_video": "https://cdn.test/selected.mp4",
                "image_candidates": [],
                "video_variants": [],
                "last_error": "previous provider timeout",
            }
        ],
        production_run=None,
    )
    stream = _build_stream(events=events, nodes=[{"id": "writeback"}], limit=10)

    assert outputs["script"]["content"]
    assert {item["source"] for item in outputs["script"]["items"]} == {"tasks", "agent_steps"}
    assert outputs["director_notes"]
    assert any(item["url"] == "https://cdn.test/selected.png" for item in outputs["images"])
    assert any(item["url"] == "https://cdn.test/shot1.mp4" for item in outputs["videos"])
    assert outputs["shots"][0]["selected_image"] == "https://cdn.test/selected.png"
    assert outputs["shots"][0]["selected_video"] == "https://cdn.test/selected.mp4"
    assert outputs["shots"][0]["last_error"] == "previous provider timeout"
    assert events[1]["debug"] == {"tokens": 12}
    assert [item["id"] for item in stream] == ["event-decision"]
    assert stream[0]["summary"] == "DeepSeek chose plan_visual_assets"
    assert stream[0]["reason"] == "reference image rejected"


def test_provider_failure_event_has_recovery_action_and_explainable_error():
    event = _shared._build_task_agent_event(
        "task-1",
        "error",
        {"tool": "seedance", "error": "provider timeout", "error_reason": "Seedance timed out", "retryable": True, "recovery": "change_provider"},
        {"run_id": "run-1", "project_id": "project-1", "user_id": 7, "task_type": "video_gen"},
    )

    assert event["actor"] == "seedance"
    assert event["event_kind"] == "error"
    assert event["status"] == "blocked"
    assert event["summary"]
    assert event["reason"] == "Seedance timed out"
    assert event["detail"] != "error"
    assert event["meta"]["recovery"] == "change_provider"


def test_frontend_output_board_renders_outputs_without_main_screen_evidence_json():
    component = (ROOT / "frontend" / "src" / "pages" / "director" / "agent-run" / "components" / "OutputBoard.vue").read_text(encoding="utf-8")
    page = (ROOT / "frontend" / "src" / "pages" / "director" / "agent-run" / "[runId].vue").read_text(encoding="utf-8")

    assert "<OutputBoard" in page
    assert "v-if=\"showOutputs\"" in page
    assert ":run-id=\"runId\"" in page
    assert ":outputs=\"snapshot?.outputs || null\"" in page
    assert "@refresh=\"refresh\"" in page
    assert "scriptContent" in component
    assert "images.length" in component
    assert "videos.length" in component
    assert "director_notes" in component
    assert "keyframe_pool" in component
    assert "evidence" not in component.lower()
    assert "<pre" not in component.lower()
