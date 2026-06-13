from unittest.mock import AsyncMock

import pytest

from app.services.agent_action_executor import ActionContext, dispatch_agent_action


def _active_tasks(active: bool) -> dict:
    if not active:
        return {"count": 0, "task_ids": [], "statuses": [], "items": []}
    return {
        "count": 1,
        "task_ids": ["task-a"],
        "statuses": ["running"],
        "items": [
            {
                "task_id": "task-a",
                "task_type": "video_gen",
                "status": "running",
                "progress": 48,
                "stage_text": "Seedance 图生视频",
                "provider": "seedance",
                "shot_index": 3,
            }
        ],
    }


def _context(action: str, *, active_count: int = 0) -> ActionContext:
    return ActionContext(
        run_id="run-1",
        project_id="project-1",
        user_id=7,
        action=action,
        instruction="参考图不行",
        routing={"resolved_action": action},
        continue_body={"action": action},
        current_status="dispatching",
        active_tasks=_active_tasks(active_count > 0),
    )


@pytest.mark.asyncio
async def test_status_query_executor_answers_without_dispatch():
    execute = AsyncMock()

    result = await dispatch_agent_action(_context("status_query", active_count=1), execute_continue_project=execute)

    assert result is not None
    assert result.status == "answered"
    assert result.executor == "StatusQueryExecutor"
    assert "当前 Run 状态是 dispatching" in result.answer
    assert "视频生成" in result.answer
    assert "第 3 镜" in result.answer
    assert "provider seedance" in result.answer
    assert "进度 48%" in result.answer
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_visual_asset_executor_returns_requested_action_intent_when_idle():
    execute = AsyncMock(return_value={"run_id": "run-2", "status": "completed"})

    result = await dispatch_agent_action(_context("plan_visual_assets"), execute_continue_project=execute)

    assert result is not None
    assert result.status == "requested_action"
    assert result.executor == "ActionIntentExecutor"
    assert result.result["requested_action"] == "plan_visual_assets"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_edit_executor_returns_requested_action_intent_when_idle():
    execute_continue = AsyncMock()
    execute_final_edit = AsyncMock(return_value={"task_id": "export-task-1", "status": "queued", "clip_count": 3})

    result = await dispatch_agent_action(
        _context("plan_final_edit"),
        execute_continue_project=execute_continue,
        execute_final_edit=execute_final_edit,
    )

    assert result is not None
    assert result.status == "requested_action"
    assert result.executor == "ActionIntentExecutor"
    assert result.result["requested_action"] == "plan_final_edit"
    execute_final_edit.assert_not_awaited()
    execute_continue.assert_not_awaited()


@pytest.mark.asyncio
async def test_executor_defers_non_status_action_when_active():
    execute = AsyncMock()

    result = await dispatch_agent_action(_context("plan_visual_assets", active_count=1), execute_continue_project=execute)

    assert result is not None
    assert result.status == "deferred"
    assert result.executor == "DeferredInstructionExecutor"
    assert "已接收你的指令，路由到 参考图和视觉资产" in result.answer
    assert "视频生成" in result.answer
    assert "Seedance 图生视频" in result.answer
    assert "资产不一致" in result.answer
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_executor_defers_production_action_when_active():
    execute = AsyncMock()

    result = await dispatch_agent_action(_context("generate_videos", active_count=1), execute_continue_project=execute)

    assert result is not None
    assert result.status == "deferred"
    assert result.executor == "DeferredInstructionExecutor"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_production_action_returns_requested_action_intent():
    execute = AsyncMock()

    result = await dispatch_agent_action(_context("generate_videos"), execute_continue_project=execute)

    assert result is not None
    assert result.status == "requested_action"
    assert result.executor == "ActionIntentExecutor"
    assert result.result["requested_action"] == "generate_videos"
    execute.assert_not_awaited()
