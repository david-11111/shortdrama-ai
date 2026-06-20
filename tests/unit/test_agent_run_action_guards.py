import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.services.llm_planner import PlannerDecision


ROOT = Path(__file__).resolve().parents[2]


def _load_agent_runs(monkeypatch):
    routes_pkg = types.ModuleType("app.routes")
    routes_pkg.__path__ = []
    director = types.ModuleType("app.routes.director")
    workbench = types.ModuleType("app.routes.workbench")

    async def director_export_preview(**_kwargs):
        return {"task_id": "export-task-1", "status": "queued"}

    async def continue_project_brain(**_kwargs):
        return {"run_id": "run-1", "status": "queued"}

    async def start_video_production(**_kwargs):
        return {"agent_run_id": "run-1", "status": "queued"}

    director.director_export_preview = director_export_preview
    workbench.continue_project_brain = continue_project_brain
    workbench.start_video_production = start_video_production

    monkeypatch.setitem(sys.modules, "app.routes", routes_pkg)
    monkeypatch.setitem(sys.modules, "app.routes.director", director)
    monkeypatch.setitem(sys.modules, "app.routes.workbench", workbench)

    spec = importlib.util.spec_from_file_location("agent_runs_under_test", ROOT / "app" / "routes" / "agent_runs.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_cancel_is_idempotent_after_run_is_already_cancelled(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)
    db = object()

    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="cancelled"))
    cancel_tasks = AsyncMock()
    update_run = AsyncMock()
    publish_event = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(agent_runs, "_cancel_queued_run_tasks", cancel_tasks)
    monkeypatch.setattr(agent_runs, "update_agent_run", update_run)
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish_event)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", audit)

    result = await agent_runs.cancel_run("run-1", db=db, current_user={"id": 7})

    assert result == {
        "run_id": "run-1",
        "project_id": "project-1",
        "action": "cancel_run",
        "status": "cancelled",
        "idempotent": True,
        "cancelled_count": 0,
        "cancelled_task_ids": [],
        "refunded_credits": 0,
    }
    cancel_tasks.assert_not_awaited()
    update_run.assert_not_awaited()
    publish_event.assert_not_awaited()
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_guard_blocks_when_run_has_active_tasks(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 2, "task_ids": ["task-a", "task-b"], "statuses": ["queued", "running"]}),
    )

    with pytest.raises(HTTPException) as exc:
        await agent_runs._ensure_run_can_dispatch(object(), run_id="run-1", user_id=7, action="continue_step")

    assert exc.value.status_code == 409
    assert exc.value.detail["action"] == "continue_step"
    assert exc.value.detail["run_id"] == "run-1"
    assert exc.value.detail["active_task_count"] == 2
    assert exc.value.detail["active_task_ids"] == ["task-a", "task-b"]
    assert exc.value.detail["active_task_statuses"] == ["queued", "running"]


@pytest.mark.asyncio
async def test_action_gate_blocks_video_when_keyframes_are_missing(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    publish = AsyncMock(return_value={"id": "event-1"})
    monkeypatch.setattr(
        agent_runs,
        "_run_production_state",
        AsyncMock(return_value={"shots": [{"shot_index": 1, "prompt": "shot"}], "tasks": [], "production_run": None}),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)

    with pytest.raises(HTTPException) as exc:
        await agent_runs._ensure_action_gate_allows(
            _Db(),
            run_id="run-1",
            project_id="project-1",
            user_id=7,
            action="generate_videos",
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["action"] == "generate_videos"
    assert "selected_image" in exc.value.detail["missing"]
    assert exc.value.detail["reason"]
    assert exc.value.detail["recovery"] == "generate_keyframes"
    event = publish.await_args.kwargs
    assert event["actor"] == "state_machine"
    assert event["event_kind"] == "guardrail"
    assert event["summary"] == "状态机阻止视频生成越级执行"
    assert event["reason"]
    assert "selected_image" in event["meta"]["missing"]
    assert event["meta"]["gate"]["recovery"] == "generate_keyframes"
    assert "generate_keyframes" in event["meta"]["available_actions"]


@pytest.mark.asyncio
async def test_action_gate_blocks_video_when_keyframe_review_needs_confirmation(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    publish = AsyncMock(return_value={"id": "event-1"})
    monkeypatch.setattr(
        agent_runs,
        "_run_production_state",
        AsyncMock(
            return_value={
                "shots": [
                    {
                        "shot_index": 1,
                        "prompt": "shot",
                        "selected_image": "image.png",
                        "selected_video": "",
                        "image_candidates": [{"url": "image.png", "review_status": "needs_review"}],
                    }
                ],
                "tasks": [],
                "production_run": None,
            }
        ),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)

    with pytest.raises(HTTPException) as exc:
        await agent_runs._ensure_action_gate_allows(
            _Db(),
            run_id="run-1",
            project_id="project-1",
            user_id=7,
            action="generate_videos",
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["action"] == "generate_videos"
    assert "image_review_blockers" in exc.value.detail["missing"]
    assert exc.value.detail["recovery"] == "generate_keyframes"
    assert exc.value.detail["available_actions"] == ["generate_keyframes", "ask_human"]
    event = publish.await_args.kwargs
    assert event["visibility"] == "user"
    assert event["event_kind"] == "guardrail"
    assert "image_review_blockers" in event["meta"]["missing"]
    assert event["meta"]["gate"]["recovery"] == "generate_keyframes"


@pytest.mark.asyncio
async def test_action_gate_blocks_final_edit_when_video_review_needs_regeneration(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    publish = AsyncMock(return_value={"id": "event-1"})
    monkeypatch.setattr(
        agent_runs,
        "_run_production_state",
        AsyncMock(
            return_value={
                "shots": [
                    {
                        "shot_index": 1,
                        "prompt": "shot",
                        "selected_image": "image.png",
                        "selected_video": "video.mp4",
                        "video_variants": [{"url": "video.mp4", "review_status": "regenerate"}],
                    }
                ],
                "tasks": [],
                "production_run": None,
            }
        ),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)

    with pytest.raises(HTTPException) as exc:
        await agent_runs._ensure_action_gate_allows(
            _Db(),
            run_id="run-1",
            project_id="project-1",
            user_id=7,
            action="plan_final_edit",
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["action"] == "plan_final_edit"
    assert "video_review_blockers" in exc.value.detail["missing"]
    assert exc.value.detail["recovery"] == "generate_videos"
    assert exc.value.detail["available_actions"] == ["generate_videos", "ask_human"]
    event = publish.await_args.kwargs
    assert event["visibility"] == "user"
    assert event["event_kind"] == "guardrail"
    assert "video_review_blockers" in event["meta"]["missing"]
    assert event["meta"]["gate"]["recovery"] == "generate_videos"


@pytest.mark.asyncio
async def test_continue_step_defers_production_action_when_tasks_are_active(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    audit = AsyncMock()
    publish = AsyncMock(return_value={"id": "event-1"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 1, "task_ids": ["task-a"], "statuses": ["running"]}),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", audit)
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "视频动作不行，重新生成视频"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "deferred"
    assert "已接收你的指令" in result["answer"]
    assert result["active_tasks"]["task_ids"] == ["task-a"]
    assert result["routing"]["resolved_action"] == "generate_videos"
    continue_brain.assert_not_awaited()
    assert publish.await_count == 2
    deferred_event_meta = publish.await_args_list[1].kwargs["meta"]
    assert deferred_event_meta["pending_instruction"]["status"] == "queued"
    assert deferred_event_meta["pending_instruction"]["instruction"] == "视频动作不行，重新生成视频"
    assert deferred_event_meta["pending_instruction"]["continue_body"]["action"] == "generate_videos"
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_continue_step_dispatches_visual_asset_executor_when_idle(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "completed"})
    audit = AsyncMock()
    publish = AsyncMock(return_value={"id": "event-1"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": []}),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", audit)
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "reference image is bad, redo it"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "dispatched"
    assert result["executor"] == "VisualAssetExecutor"
    assert result["result"] == {"run_id": "run-2", "status": "completed"}
    continue_brain.assert_awaited_once()
    dispatch_event = publish.await_args_list[-1].kwargs
    assert dispatch_event["actor"] == "executor"
    assert dispatch_event["event_kind"] == "dispatch"
    assert dispatch_event["status"] == "dispatched"
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_continue_step_dispatches_final_edit_executor_when_idle(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    export_preview = AsyncMock(return_value={"task_id": "export-task-1", "status": "queued", "clip_count": 3})
    audit = AsyncMock()
    publish = AsyncMock(return_value={"id": "event-1"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(agent_runs, "_ensure_no_active_export", AsyncMock())
    monkeypatch.setattr(
        agent_runs,
        "_selected_video_rows",
        AsyncMock(
            return_value=[
                {"shot_index": 1, "selected_video": "https://cdn.test/1.mp4"},
                {"shot_index": 2, "selected_video": "https://cdn.test/2.mp4"},
                {"shot_index": 3, "selected_video": "https://cdn.test/3.mp4"},
            ]
        ),
    )
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", audit)
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)
    monkeypatch.setattr(agent_runs, "director_export_preview", export_preview)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "开始剪辑成片", "continue_action": "plan_final_edit"},
        db=_Db(),
        current_user={"id": 7, "tier": "pro"},
    )

    assert result["status"] == "dispatched"
    assert result["executor"] == "FinalEditExecutor"
    assert result["result"]["task_id"] == "export-task-1"
    assert result["result"]["shot_indices"] == [1, 2, 3]
    continue_brain.assert_not_awaited()
    export_preview.assert_awaited_once()
    export_body = export_preview.await_args.kwargs["body"]
    assert export_body["action"] == "plan_final_edit"
    assert export_body["project_id"] == "project-1"
    assert export_body["run_id"] == "run-1"
    assert export_body["ignore_saved_plan"] is True
    dispatch_event = publish.await_args_list[-1].kwargs
    assert dispatch_event["summary"] == "已派发剪辑成片"
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_continue_step_blocks_final_edit_when_selected_video_urls_expired(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    expired_url = (
        "https://ark.test/video.mp4?"
        "X-Tos-Date=20260521T134511Z&X-Tos-Expires=86400&X-Tos-Signature=x"
    )
    publish = AsyncMock(return_value={"id": "event-1"})
    save_pending = AsyncMock()
    export_preview = AsyncMock()
    continue_brain = AsyncMock()
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(agent_runs, "_ensure_no_active_export", AsyncMock())
    monkeypatch.setattr(
        agent_runs,
        "_selected_video_rows",
        AsyncMock(return_value=[{"shot_index": 1, "selected_video": expired_url}]),
    )
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "_save_pending_action", save_pending)
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)
    monkeypatch.setattr(agent_runs, "director_export_preview", export_preview)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "开始剪辑成片", "continue_action": "plan_final_edit"},
        db=_Db(),
        current_user={"id": 7, "tier": "pro"},
    )

    assert result["status"] == "answered"
    assert result["executor"] == "FinalEditExecutor"
    assert result["result"]["status"] == "blocked"
    assert result["pending_action"]["action"] == "generate_videos"
    assert "视频链接已经过期" in result["answer"]
    export_preview.assert_not_awaited()
    continue_brain.assert_not_awaited()
    save_pending.assert_awaited_once()


@pytest.mark.asyncio
async def test_continue_step_emits_deepseek_planner_decision_event(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    planner = PlannerDecision(
        action="plan_visual_assets",
        confidence=0.92,
        reason="Reference-image feedback belongs to the visual asset loop.",
        target={"shot_index": 2},
        source="deepseek",
    )
    publish = AsyncMock(return_value={"id": "event-1"})
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "completed"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=planner))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "the reference image is wrong, redo it"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "dispatched"
    planner_event = publish.await_args_list[0].kwargs
    assert planner_event["source"] == "deepseek"
    assert planner_event["event_type"] == "decision"
    assert planner_event["phase"] == "llm_planner"
    assert planner_event["status"] == "done"
    assert planner_event["meta"]["planner"]["action"] == "plan_visual_assets"
    assert planner_event["meta"]["planner"]["confidence"] == 0.92
    assert "DeepSeek" in planner_event["title"]


@pytest.mark.asyncio
async def test_continue_step_lets_deepseek_answer_before_dispatch(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    planner = PlannerDecision(
        action="status_query",
        confidence=0.94,
        reason="User is asking why several reference images are not visible, so DeepSeek must diagnose first.",
        target={"surface": "output_board", "asset_type": "reference_image"},
        source="deepseek",
        intent_type="ui_diagnostic",
        reply="我先按成果区显示问题排查，不会重新生成。需要检查这些参考图 URL 是否过期、403 或加载失败。",
        dispatch_ready=False,
        missing_info=["具体是哪几张参考图或镜头"],
        extracted={"issue_type": "missing_reference_images"},
    )
    publish = AsyncMock(return_value={"id": "event-1"})
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    audit = AsyncMock()
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=planner))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 1, "task_ids": ["task-a"], "statuses": ["running"], "items": []}),
    )
    monkeypatch.setattr(
        agent_runs,
        "_build_control_diagnostics",
        AsyncMock(return_value={"outputs": {"tool_name": "diagnose_outputs", "recommended_action": "repair_missing_images"}}),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", audit)
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)
    ensure_gate = AsyncMock()
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", ensure_gate)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "有几张参考图没有显示出来查看什么原因?", "action_hint": "plan_visual_assets"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "answered"
    assert result["executor"] == "OutputDiagnosticExecutor"
    assert "followup_action" not in result
    assert "后续处理动作暂存" not in result["answer"]
    assert result["routing"]["planner"]["dispatch_ready"] is False
    continue_brain.assert_not_awaited()
    ensure_gate.assert_not_awaited()
    response_event = next(item.kwargs for item in publish.await_args_list if item.kwargs["phase"] == "human_response")
    assert response_event["phase"] == "human_response"
    assert response_event["actor"] == "deepseek"
    assert response_event["meta"]["executor"] == "OutputDiagnosticExecutor"
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_continue_step_runs_output_diagnostic_tool_without_deepseek(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    publish = AsyncMock(return_value={"id": "event-1"})
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}),
    )
    monkeypatch.setattr(
        agent_runs,
        "get_agent_run_snapshot",
        AsyncMock(
            return_value={
                "outputs": {
                    "summary": {"image_count": 1, "shot_count": 2},
                    "images": [{"url": "https://cdn.test/a.png?Expires=1&Signature=x", "shot_index": 1}],
                    "shots": [
                        {"shot_index": 1, "selected_image": "https://cdn.test/a.png?Expires=1&Signature=x"},
                        {"shot_index": 2, "selected_image": ""},
                    ],
                }
            }
        ),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)
    ensure_gate = AsyncMock()
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", ensure_gate)
    monkeypatch.setattr(agent_runs, "compose_evidence_reply", AsyncMock(return_value=None))

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "有几张参考图没显示，查一下原因"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "answered"
    assert result["executor"] == "OutputDiagnosticExecutor"
    assert result["routing"]["routing_source"] == "control_tool"
    assert result["routing"]["control_tool"]["tool_name"] == "diagnose_outputs"
    assert "第 2 镜" in result["answer"]
    continue_brain.assert_not_awaited()
    ensure_gate.assert_not_awaited()
    response_event = publish.await_args_list[-1].kwargs
    assert response_event["phase"] == "human_response"


@pytest.mark.asyncio
async def test_continue_step_uses_evidence_composer_reply(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    class _Composition:
        def as_dict(self):
            return {
                "reply": "我查了证据：第 2 镜没有 selected_image，下一步应补齐这张图。",
                "recommended_action": "repair_missing_images",
                "dispatch_ready": True,
                "reason": "tool result shows missing selected_image",
                "needs_human": False,
                "source": "deepseek",
            }

    publish = AsyncMock(return_value={"id": "event-1"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}),
    )
    monkeypatch.setattr(
        agent_runs,
        "get_agent_run_snapshot",
        AsyncMock(
            return_value={
                "outputs": {
                    "images": [],
                    "shots": [{"shot_index": 2, "selected_image": ""}],
                    "summary": {"image_count": 0, "shot_count": 1},
                }
            }
        ),
    )
    compose = AsyncMock(return_value=_Composition())
    monkeypatch.setattr(agent_runs, "compose_evidence_reply", compose)
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "continue_project_brain", AsyncMock(return_value={"run_id": "run-2", "status": "queued"}))

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "有几张参考图没显示，查一下原因"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["answer"] == "我查了证据：第 2 镜没有 selected_image，下一步应补齐这张图。"
    assert result["status"] == "answered"
    assert result["evidence_composer"]["recommended_action"] == "repair_missing_images"
    assert "followup_action" not in result
    compose.assert_awaited_once()
    response_event = next(item.kwargs for item in publish.await_args_list if item.kwargs["phase"] == "human_response")
    assert response_event["meta"]["evidence_composer"]["source"] == "deepseek"
    assert response_event["summary"] == "我查了证据：第 2 镜没有 selected_image，下一步应补齐这张图。"


@pytest.mark.asyncio
async def test_continue_step_dispatches_followup_action_from_diagnostic_when_idle(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    publish = AsyncMock(return_value={"id": "event-1"})
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}),
    )
    monkeypatch.setattr(
        agent_runs,
        "get_agent_run_snapshot",
        AsyncMock(return_value={"outputs": {"images": [], "shots": [{"shot_index": 2, "selected_image": ""}]}}),
    )
    monkeypatch.setattr(agent_runs, "compose_evidence_reply", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "有几张参考图没显示，查一下原因"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "answered"
    assert "followup_action" not in result
    continue_brain.assert_not_awaited()
    dispatch_event = publish.await_args_list[-1].kwargs
    assert dispatch_event["phase"] == "human_response"


@pytest.mark.asyncio
async def test_continue_step_defers_followup_action_from_diagnostic_when_busy(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    publish = AsyncMock(return_value={"id": "event-1"})
    continue_brain = AsyncMock()
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 1, "task_ids": ["task-a"], "statuses": ["running"], "items": []}),
    )
    monkeypatch.setattr(
        agent_runs,
        "get_agent_run_snapshot",
        AsyncMock(return_value={"outputs": {"images": [], "shots": [{"shot_index": 2, "selected_image": ""}]}}),
    )
    monkeypatch.setattr(agent_runs, "compose_evidence_reply", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "有几张参考图没显示，查一下原因"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "answered"
    assert "followup_action" not in result
    assert "pending_instruction" not in result
    continue_brain.assert_not_awaited()
    deferred_event = publish.await_args_list[-1].kwargs
    assert deferred_event["status"] == "done"


@pytest.mark.asyncio
async def test_continue_step_runs_task_diagnostic_tool(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    publish = AsyncMock(return_value={"id": "event-1"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 1, "task_ids": ["task-a"], "statuses": ["running"], "items": []}),
    )
    monkeypatch.setattr(
        agent_runs,
        "get_agent_run_snapshot",
        AsyncMock(return_value={"tasks": [{"task_id": "task-a", "task_type": "video_gen", "status": "running", "payload": {"shot_index": 2}}]}),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "compose_evidence_reply", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "task stuck in queue, check it"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "answered"
    assert result["executor"] == "TaskDiagnosticExecutor"
    assert result["routing"]["control_tool"]["tool_name"] == "diagnose_tasks"
    assert "任务队列" in result["answer"]
    continue_brain.assert_not_awaited()
    response_event = publish.await_args_list[-1].kwargs
    assert response_event["meta"]["tool_result"]["diagnose_tasks"]["recommended_action"] == "wait_active_tasks"


@pytest.mark.asyncio
async def test_continue_step_runs_provider_writeback_diagnostic_tool(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    publish = AsyncMock(return_value={"id": "event-1"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}),
    )
    monkeypatch.setattr(
        agent_runs,
        "get_agent_run_snapshot",
        AsyncMock(
            return_value={
                "tasks": [
                    {
                        "task_id": "task-img",
                        "task_type": "image_gen",
                        "status": "completed",
                        "payload": {"shot_index": 4, "provider": "seedream"},
                        "result": {"image_url": "https://cdn.test/4.png"},
                    }
                ],
                "outputs": {"shots": [{"shot_index": 4, "selected_image": "", "selected_video": ""}]},
                "events": {"user": []},
            }
        ),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "compose_evidence_reply", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "seedream result did not writeback selected_image"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "answered"
    assert result["executor"] == "ProviderWritebackDiagnosticExecutor"
    assert result["routing"]["control_tool"]["tool_name"] == "diagnose_provider_writeback"
    assert "写回链路" in result["answer"]
    assert "followup_action" not in result
    continue_brain.assert_not_awaited()
    response_event = publish.await_args_list[-1].kwargs
    assert response_event["phase"] == "human_response"


@pytest.mark.asyncio
async def test_continue_step_dispatches_story_plan_from_script_diagnostic(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    publish = AsyncMock(return_value={"id": "event-1"})
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}),
    )
    monkeypatch.setattr(
        agent_runs,
        "get_agent_run_snapshot",
        AsyncMock(
            return_value={
                "outputs": {
                    "script": {"content": "旧剧本：主角直接介绍产品。", "items": [{"content": "旧剧本：主角直接介绍产品。"}]},
                    "director_notes": [{"title": "导演建议", "content": "开场偏平。"}],
                    "shots": [{"shot_index": 1, "prompt": "主角介绍产品", "duration": 3, "status": "planned"}],
                }
            }
        ),
    )
    monkeypatch.setattr(agent_runs, "compose_evidence_reply", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "把第1镜前三秒钩子和产品卖点加强，重写剧本分镜"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "dispatched"
    assert result["executor"] == "ScriptDiagnosticExecutor"
    assert result["routing"]["control_tool"]["tool_name"] == "diagnose_script"
    assert result["followup_action"] == "generate_story_plan"
    continue_brain.assert_awaited_once()
    assert continue_brain.await_args.kwargs["body"]["action"] == "generate_story_plan"
    assert continue_brain.await_args.kwargs["body"]["instruction"] == "把第1镜前三秒钩子和产品卖点加强，重写剧本分镜"


@pytest.mark.asyncio
async def test_continue_step_defers_story_plan_from_script_diagnostic_when_busy(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    publish = AsyncMock(return_value={"id": "event-1"})
    continue_brain = AsyncMock()
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 1, "task_ids": ["task-a"], "statuses": ["running"], "items": []}),
    )
    monkeypatch.setattr(
        agent_runs,
        "get_agent_run_snapshot",
        AsyncMock(return_value={"outputs": {"script": {"content": "旧剧本"}, "shots": [{"shot_index": 1, "prompt": "旧分镜"}]}}),
    )
    monkeypatch.setattr(agent_runs, "compose_evidence_reply", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "剧本节奏太慢，重写分镜"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "deferred"
    assert result["followup_action"] == "generate_story_plan"
    assert result["pending_instruction"]["continue_body"]["action"] == "generate_story_plan"
    continue_brain.assert_not_awaited()


@pytest.mark.asyncio
async def test_continue_step_dispatches_keyframes_from_keyframe_pool_batch_request(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    publish = AsyncMock(return_value={"id": "event-1"})
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}),
    )
    monkeypatch.setattr(
        agent_runs,
        "get_agent_run_snapshot",
        AsyncMock(
            return_value={
                "outputs": {
                    "shots": [
                        {
                            "shot_index": 3,
                            "prompt": "主角拿起产品",
                            "selected_image": "https://cdn.test/main.png",
                            "image_candidates": [{"url": "https://cdn.test/alt.png"}],
                        }
                    ],
                    "images": [],
                }
            }
        ),
    )
    monkeypatch.setattr(agent_runs, "compose_evidence_reply", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "第3镜多做几张图，角度丰富一点"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "dispatched"
    assert result["executor"] == "KeyframePoolDiagnosticExecutor"
    assert result["routing"]["control_tool"]["tool_name"] == "diagnose_keyframe_pool"
    assert result["followup_action"] == "generate_keyframes"
    continue_brain.assert_awaited_once()
    assert continue_brain.await_args.kwargs["body"]["action"] == "generate_keyframes"


@pytest.mark.asyncio
async def test_continue_step_confirm_uses_saved_pending_action_before_planner(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    planner = AsyncMock(return_value=None)
    audit = AsyncMock()
    publish = AsyncMock(return_value={"id": "event-1"})

    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(
        agent_runs,
        "_load_pending_action",
        AsyncMock(return_value={"action": "generate_videos", "domain": "video", "recommendation": "repair_missing_videos"}),
    )
    monkeypatch.setattr(agent_runs, "plan_human_instruction", planner)
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="failed"))
    monkeypatch.setattr(agent_runs, "_active_run_task_summary", AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", audit)
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "好，执行吧"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["action"] == "continue_step"
    assert result["routing"]["routing_source"] == "pending_action_confirm"
    assert result["routing"]["resolved_action"] == "generate_videos"
    planner.assert_not_awaited()
    continue_brain.assert_awaited_once()
    assert continue_brain.await_args.kwargs["body"]["action"] == "generate_videos"
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_continue_step_execute_phrase_confirms_saved_pending_action(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    pending_action = {
        "action": "generate_keyframes",
        "domain": "keyframe",
        "recommendation": "regenerate_review_failed_keyframes",
        "shot_indices": [1, 2, 3],
        "continue_body": {"action": "generate_keyframes"},
    }
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    planner = AsyncMock(return_value=None)

    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "_load_pending_action", AsyncMock(return_value=pending_action))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", planner)
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="failed"))
    monkeypatch.setattr(agent_runs, "_active_run_task_summary", AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(agent_runs, "publish_agent_event", AsyncMock(return_value={"id": "event-1"}))
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "执行"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["routing"]["routing_source"] == "pending_action_confirm"
    assert result["routing"]["resolved_action"] == "generate_keyframes"
    planner.assert_not_awaited()
    continue_brain.assert_awaited_once()
    assert continue_brain.await_args.kwargs["body"]["action"] == "generate_keyframes"
    assert continue_brain.await_args.kwargs["body"]["human_routing"]["pending_action"]["recommendation"] == "regenerate_review_failed_keyframes"


@pytest.mark.asyncio
async def test_state_machine_recovery_returns_generate_keyframes_body(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)
    production_state = {
        "shots": [
            {
                "shot_index": 1,
                "prompt": "shot",
                "selected_image": "https://cdn.test/shot-1.png",
                "selected_video": "",
                "image_candidates": [
                    {"url": "https://cdn.test/shot-1.png", "review_status": "regenerate"}
                ],
            }
        ],
        "tasks": [],
        "production_run": None,
    }
    monkeypatch.setattr(agent_runs, "_run_production_state", AsyncMock(return_value=production_state))

    continue_body, routing = await agent_runs._apply_state_machine_recovery_routing(
        object(),
        {"instruction": "continue"},
        {
            "instruction": "continue",
            "intent_type": "production_action",
            "action_ceiling": "execute_allowed",
            "utterance_type": "command",
            "planner": {
                "action": "generate_keyframes",
                "intent_type": "production_action",
                "dispatch_ready": False,
            },
        },
        run_id="run-1",
        project_id="project-1",
        user_id=7,
    )

    assert continue_body["action"] == "generate_keyframes"
    assert continue_body["continue_action"] == "generate_keyframes"
    assert routing["routing_source"] == "state_machine_recovery"
    assert routing["resolved_action"] == "generate_keyframes"
    assert routing["state_machine_recovery"]["missing"] == ["image_review_blockers"]


@pytest.mark.asyncio
async def test_review_blocker_recovery_dispatches_regenerate_keyframes(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)
    production_state = {
        "shots": [
            {
                "shot_index": 1,
                "prompt": "shot",
                "selected_image": "https://cdn.test/shot-1.png",
                "selected_video": "",
                "image_candidates": [
                    {
                        "url": "https://cdn.test/shot-1.png",
                        "review_status": "regenerate",
                        "review": {"missing_reference_assets": ["character"]},
                    }
                ],
            }
        ],
        "tasks": [],
        "production_run": None,
    }
    save_pending = AsyncMock()
    monkeypatch.setattr(agent_runs, "_run_production_state", AsyncMock(return_value=production_state))
    monkeypatch.setattr(agent_runs, "_save_pending_action", save_pending)

    continue_body, routing = await agent_runs._apply_review_blocker_clarification_routing(
        object(),
        {
            "instruction": "continue",
            "action": "generate_keyframes",
            "continue_action": "generate_keyframes",
        },
        {
            "instruction": "continue",
            "resolved_action": "generate_keyframes",
            "routing_source": "state_machine_recovery",
            "intent_type": "production_action",
            "action_ceiling": "execute_allowed",
        },
        run_id="run-1",
        project_id="project-1",
        user_id=7,
    )

    assert continue_body["action"] == "generate_keyframes"
    assert continue_body["continue_action"] == "generate_keyframes"
    assert continue_body["shot_indices"] == [1]
    assert routing["resolved_action"] == "generate_keyframes"
    assert routing["review_blocker_clarification"]["proposal"]["recommendation"] == "regenerate_review_failed_keyframes"
    save_pending.assert_not_awaited()


@pytest.mark.asyncio
async def test_continue_step_confirm_approves_review_pending_keyframes_before_video(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    pending_action = {
        "action": "generate_videos",
        "domain": "video",
        "recommendation": "approve_review_pending_keyframes",
        "shot_indices": [1, 2],
        "continue_body": {"action": "generate_videos"},
    }
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    approve = AsyncMock()
    ensure_gate = AsyncMock()

    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "_load_pending_action", AsyncMock(return_value=pending_action))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="failed"))
    monkeypatch.setattr(agent_runs, "_active_run_task_summary", AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", ensure_gate)
    monkeypatch.setattr(agent_runs, "_approve_review_pending_keyframes", approve)
    monkeypatch.setattr(agent_runs, "publish_agent_event", AsyncMock(return_value={"id": "event-1"}))
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "继续"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["routing"]["routing_source"] == "pending_action_confirm"
    assert result["routing"]["resolved_action"] == "generate_videos"
    approve.assert_awaited_once()
    assert approve.await_args.kwargs["project_id"] == "project-1"
    assert approve.await_args.kwargs["user_id"] == 7
    assert approve.await_args.kwargs["shot_indices"] == [1, 2]
    assert ensure_gate.await_count >= 1
    continue_brain.assert_awaited_once()
    assert continue_brain.await_args.kwargs["body"]["action"] == "generate_videos"


@pytest.mark.asyncio
async def test_continue_step_confirm_approves_review_pending_videos_before_final_edit(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    pending_action = {
        "action": "plan_final_edit",
        "domain": "final_edit",
        "recommendation": "approve_review_pending_videos",
        "shot_indices": [1, 2],
        "continue_body": {"action": "plan_final_edit"},
    }
    continue_brain = AsyncMock(return_value={"run_id": "run-3", "status": "queued"})
    approve = AsyncMock()
    ensure_gate = AsyncMock()

    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "_load_pending_action", AsyncMock(return_value=pending_action))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="completed"))
    monkeypatch.setattr(agent_runs, "_active_run_task_summary", AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", ensure_gate)
    monkeypatch.setattr(agent_runs, "_approve_review_pending_videos", approve)
    monkeypatch.setattr(agent_runs, "publish_agent_event", AsyncMock(return_value={"id": "event-1"}))
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "继续"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["routing"]["routing_source"] == "pending_action_confirm"
    assert result["routing"]["resolved_action"] == "plan_final_edit"
    approve.assert_awaited_once()
    assert approve.await_args.kwargs["project_id"] == "project-1"
    assert approve.await_args.kwargs["user_id"] == 7
    assert approve.await_args.kwargs["shot_indices"] == [1, 2]
    assert ensure_gate.await_count >= 1
    continue_brain.assert_awaited_once()
    assert continue_brain.await_args.kwargs["body"]["action"] == "plan_final_edit"


@pytest.mark.asyncio
async def test_continue_step_asks_for_keyframe_revision_details_after_review_block(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    planner = PlannerDecision(
        action="generate_keyframes",
        confidence=0.82,
        reason="Keyword hit keyframe generation.",
        target={},
        source="deepseek",
        intent_type="production_action",
        reply="Continue keyframe generation.",
        dispatch_ready=True,
        missing_info=[],
    )
    production_state = {
        "shots": [
            {
                "shot_index": 1,
                "prompt": "shot",
                "selected_image": "https://cdn.test/shot-1.png",
                "image_candidates": [{"review": {"status": "needs_review"}}],
            }
        ],
        "tasks": [],
        "production_run": None,
    }
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    publish = AsyncMock(return_value={"id": "event-1"})
    audit = AsyncMock()
    ensure_gate = AsyncMock()
    stream_reply = AsyncMock()
    save_pending = AsyncMock()

    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=planner))
    monkeypatch.setattr(agent_runs, "_run_production_state", AsyncMock(return_value=production_state))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(agent_runs, "_active_run_task_summary", AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", ensure_gate)
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", audit)
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)
    monkeypatch.setattr(agent_runs, "stream_pregenerated_reply", stream_reply)
    monkeypatch.setattr(agent_runs, "_save_pending_action", save_pending)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "继续"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["action"] == "continue_step"
    assert result["status"] == "answered"
    assert result["executor"] == "DeepSeekConversation"
    assert result["result"] is None
    assert result["routing"]["planner"]["dispatch_ready"] is False
    assert result["routing"]["review_blocker_clarification"]["missing"] == ["image_review_blockers"]
    assert result["routing"]["pending_action"]["recommendation"] == "approve_review_pending_keyframes"
    assert result["routing"]["pending_action"]["action"] == "generate_videos"
    assert result["routing"]["pending_action"]["shot_indices"] == [1]
    assert "第1镜" in result["answer"]
    assert "确认" in result["answer"]
    continue_brain.assert_not_awaited()
    ensure_gate.assert_not_awaited()
    stream_reply.assert_awaited_once()
    save_pending.assert_awaited_once()
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_continue_keyframe_status_query_offers_review_repair_proposal(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    planner = PlannerDecision(
        action="generate_keyframes",
        confidence=0.85,
        reason="Keyframe continuation is blocked by review.",
        target={},
        source="deepseek",
        intent_type="status_query",
        reply="Please specify which keyframes to redo.",
        dispatch_ready=False,
        missing_info=["shot scope", "revision instruction"],
    )
    production_state = {
        "shots": [
            {
                "shot_index": 1,
                "prompt": "shot",
                "selected_image": "https://cdn.test/shot-1.png",
                "image_candidates": [
                    {
                        "url": "https://cdn.test/shot-1.png",
                        "review": {
                            "status": "needs_review",
                            "missing_reference_assets": ["character"],
                        },
                    }
                ],
            }
        ],
        "tasks": [],
        "production_run": None,
    }
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    save_pending = AsyncMock()

    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=planner))
    monkeypatch.setattr(agent_runs, "_run_production_state", AsyncMock(return_value=production_state))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="failed"))
    monkeypatch.setattr(agent_runs, "_active_run_task_summary", AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(agent_runs, "publish_agent_event", AsyncMock(return_value={"id": "event-1"}))
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", AsyncMock())
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)
    monkeypatch.setattr(agent_runs, "stream_pregenerated_reply", AsyncMock())
    monkeypatch.setattr(agent_runs, "_save_pending_action", save_pending)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "continue keyframe generation"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "answered"
    assert result["executor"] == "DeepSeekConversation"
    assert result["routing"]["routing_source"] == "review_blocker_clarification"
    assert result["routing"]["pending_action"]["recommendation"] == "approve_review_pending_keyframes"
    assert result["routing"]["pending_action"]["action"] == "generate_videos"
    assert "第1镜" in result["answer"]
    continue_brain.assert_not_awaited()
    save_pending.assert_awaited_once()


@pytest.mark.asyncio
async def test_continue_step_falls_back_to_continue_project_for_unmigrated_action(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    audit = AsyncMock()
    publish = AsyncMock(return_value={"id": "event-1"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="running"))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", AsyncMock())
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": []}),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", audit)
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "Regenerate keyframes", "continue_action": "generate_keyframes"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["action"] == "continue_step"
    assert result["routing"]["resolved_action"] == "generate_keyframes"
    assert result["result"] == {"run_id": "run-2", "status": "queued"}
    continue_brain.assert_awaited_once()
    assert continue_brain.await_args.kwargs["project_id"] == "project-1"
    assert continue_brain.await_args.kwargs["body"]["action"] == "generate_keyframes"
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_continue_step_answers_status_query_without_dispatch(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    continue_brain = AsyncMock()
    audit = AsyncMock()
    publish = AsyncMock(return_value={"id": "event-1"})
    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="dispatching"))
    monkeypatch.setattr(
        agent_runs,
        "_active_run_task_summary",
        AsyncMock(return_value={"count": 1, "task_ids": ["task-a"], "statuses": ["running"]}),
    )
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", audit)
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "视频谁在管，到哪一步了"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "answered"
    assert "当前 Run 状态是 dispatching" in result["answer"]
    continue_brain.assert_not_awaited()
    assert publish.await_count == 2
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_controller_diagnostic_overrides_deepseek_false_choice_and_dispatches_followup(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Db:
        async def commit(self):
            return None

    planner = PlannerDecision(
        action="status_query",
        confidence=0.8,
        reason="DeepSeek wants to ask a follow-up, but controller diagnostics should own this.",
        target={},
        source="deepseek",
        intent_type="status_query",
        reply="要修复关键帧还是检查 URL？",
        dispatch_ready=False,
    )
    continue_brain = AsyncMock(return_value={"run_id": "run-2", "status": "queued"})
    publish = AsyncMock(return_value={"id": "event-1"})
    audit = AsyncMock()
    gate = AsyncMock()

    monkeypatch.setattr(agent_runs, "_ensure_run_owner", AsyncMock(return_value="project-1"))
    monkeypatch.setattr(agent_runs, "plan_human_instruction", AsyncMock(return_value=planner))
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", AsyncMock())
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="dispatching"))
    monkeypatch.setattr(agent_runs, "_active_run_task_summary", AsyncMock(return_value={"count": 0, "task_ids": [], "statuses": [], "items": []}))
    monkeypatch.setattr(agent_runs, "_ensure_action_gate_allows", gate)
    monkeypatch.setattr(
        agent_runs,
        "_build_control_diagnostics",
        AsyncMock(return_value={"outputs": {"tool_name": "diagnose_outputs", "recommended_action": "repair_missing_images"}}),
    )
    class _Composition:
        def as_dict(self):
            return {
                "reply": "当前视频没生成，因为关键帧不完整。要修复关键帧还是检查 URL？",
                "recommended_action": "",
                "dispatch_ready": False,
                "reason": "model asked a false choice",
                "needs_human": True,
            }

    monkeypatch.setattr(agent_runs, "compose_evidence_reply", AsyncMock(return_value=_Composition()))
    monkeypatch.setattr(agent_runs, "publish_agent_event", publish)
    monkeypatch.setattr(agent_runs, "_audit_agent_run_action", audit)
    monkeypatch.setattr(agent_runs, "continue_project_brain", continue_brain)

    result = await agent_runs.continue_run_step(
        "run-1",
        body={"instruction": "为何没生成视频呢"},
        db=_Db(),
        current_user={"id": 7},
    )

    assert result["status"] == "answered"
    assert "followup_action" not in result
    continue_brain.assert_not_awaited()
    gate.assert_not_awaited()
    response_event = next(item.kwargs for item in publish.await_args_list if item.kwargs["phase"] == "human_response")
    assert "我已派发补齐关键帧" not in response_event["summary"]


@pytest.mark.asyncio
async def test_dispatch_guard_blocks_completed_run(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)
    active_summary = AsyncMock()
    monkeypatch.setattr(agent_runs, "_get_run_status_for_update", AsyncMock(return_value="completed"))
    monkeypatch.setattr(agent_runs, "_active_run_task_summary", active_summary)

    with pytest.raises(HTTPException) as exc:
        await agent_runs._ensure_run_can_dispatch(object(), run_id="run-1", user_id=7, action="continue_step")

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "message": "Cannot continue_step; agent run is already completed",
        "action": "continue_step",
        "run_id": "run-1",
        "status": "completed",
    }
    active_summary.assert_not_awaited()


@pytest.mark.asyncio
async def test_export_guard_reports_existing_export_task(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Rows:
        def all(self):
            return [{"task_id": "export-task-1", "status": "queued"}]

    class _Result:
        def mappings(self):
            return _Rows()

    class _Db:
        async def execute(self, _query, _params):
            return _Result()

    with pytest.raises(HTTPException) as exc:
        await agent_runs._ensure_no_active_export(_Db(), run_id="run-1", project_id="project-1", user_id=7)

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "message": "Cannot export; an export task is already active for this run",
        "run_id": "run-1",
        "project_id": "project-1",
        "active_task_ids": ["export-task-1"],
        "active_task_statuses": ["queued"],
    }


@pytest.mark.asyncio
async def test_run_action_lock_releases_when_body_fails(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)
    acquire = AsyncMock()
    release = AsyncMock()
    db = object()
    monkeypatch.setattr(agent_runs, "_acquire_run_action_lock", acquire)
    monkeypatch.setattr(agent_runs, "_release_run_action_lock", release)

    with pytest.raises(RuntimeError, match="boom"):
        async with agent_runs._run_action_lock(db, run_id="run-1", action="continue_step"):
            raise RuntimeError("boom")

    acquire.assert_awaited_once_with(db, run_id="run-1", action="continue_step")
    release.assert_awaited_once_with(db, run_id="run-1", action="continue_step")


@pytest.mark.asyncio
async def test_run_action_lock_uses_transaction_scoped_advisory_lock(monkeypatch):
    agent_runs = _load_agent_runs(monkeypatch)

    class _Result:
        def scalar_one(self):
            return True

    class _Db:
        def __init__(self):
            self.statements = []

        async def execute(self, statement, params=None):
            self.statements.append(str(statement))
            return _Result()

    db = _Db()

    await agent_runs._acquire_run_action_lock(db, run_id="run-1", action="continue_step")

    assert any("pg_try_advisory_xact_lock" in statement for statement in db.statements)
    assert not any("pg_try_advisory_lock(" in statement for statement in db.statements)
