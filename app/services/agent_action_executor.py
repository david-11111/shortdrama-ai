from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.services.agent_control_tools import render_keyframe_pool_diagnostic_answer, render_output_diagnostic_answer, render_provider_writeback_answer, render_script_diagnostic_answer, render_task_diagnostic_answer


Executable = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ActionContext:
    run_id: str
    project_id: str
    user_id: int
    action: str
    instruction: str
    routing: dict[str, Any]
    continue_body: dict[str, Any]
    current_status: str
    active_tasks: dict[str, Any]
    diagnostics: dict[str, Any] | None = None


@dataclass(frozen=True)
class ActionExecutionResult:
    status: str
    executor: str
    audit_action: str
    result: dict[str, Any] | None = None
    answer: str = ""

    def response(self, context: ActionContext) -> dict[str, Any]:
        payload = {
            "run_id": context.run_id,
            "project_id": context.project_id,
            "action": "continue_step",
            "status": self.status,
            "executor": self.executor,
            "routing": context.routing,
            "active_tasks": context.active_tasks,
            "result": self.result,
        }
        if self.answer:
            payload["answer"] = self.answer
        return payload


async def dispatch_agent_action(
    context: ActionContext,
    *,
    execute_continue_project: Executable,
    execute_final_edit: Executable | None = None,
) -> ActionExecutionResult | None:
    if str(context.routing.get("intent_type") or "") == "ui_diagnostic":
        return ActionExecutionResult(
            status="answered",
            executor="OutputDiagnosticExecutor",
            audit_action="agent_run.output_diagnostic_answered",
            answer=_output_diagnostic_answer(context),
        )

    tool_name = str((context.routing.get("control_tool") or {}).get("tool_name") or "")
    if tool_name == "diagnose_tasks":
        return ActionExecutionResult(
            status="answered",
            executor="TaskDiagnosticExecutor",
            audit_action="agent_run.task_diagnostic_answered",
            answer=render_task_diagnostic_answer(_tool_diagnosis(context)),
        )
    if tool_name == "diagnose_provider_writeback":
        return ActionExecutionResult(
            status="answered",
            executor="ProviderWritebackDiagnosticExecutor",
            audit_action="agent_run.provider_writeback_diagnostic_answered",
            answer=render_provider_writeback_answer(_tool_diagnosis(context)),
        )
    if tool_name == "diagnose_script":
        return ActionExecutionResult(
            status="answered",
            executor="ScriptDiagnosticExecutor",
            audit_action="agent_run.script_diagnostic_answered",
            answer=render_script_diagnostic_answer(_tool_diagnosis(context)),
        )
    if tool_name == "diagnose_keyframe_pool":
        return ActionExecutionResult(
            status="answered",
            executor="KeyframePoolDiagnosticExecutor",
            audit_action="agent_run.keyframe_pool_diagnostic_answered",
            answer=render_keyframe_pool_diagnostic_answer(_tool_diagnosis(context)),
        )

    if context.action == "status_query":
        return ActionExecutionResult(
            status="answered",
            executor="StatusQueryExecutor",
            audit_action="agent_run.status_query_answered",
            answer=_status_answer(context),
        )

    if int(context.active_tasks.get("count") or 0) > 0:
        return ActionExecutionResult(
            status="deferred",
            executor="DeferredInstructionExecutor",
            audit_action="agent_run.human_instruction_deferred",
            answer=_deferred_answer(context),
        )

    if context.action in {"generate_story_plan", "plan_visual_assets", "generate_keyframes", "generate_videos", "plan_final_edit"}:
        return ActionExecutionResult(
            status="requested_action",
            executor="ActionIntentExecutor",
            audit_action="agent_run.action_intent_requested",
            result={"requested_action": context.action, "continue_body": context.continue_body},
        )

    return None


def _status_answer(context: ActionContext) -> str:
    active_count = int(context.active_tasks.get("count") or 0)
    if active_count:
        return (
            f"当前 Run 状态是 {context.current_status}；"
            f"有 {active_count} 个活动任务正在执行：{_active_tasks_sentence(context.active_tasks)}。"
            "你的查询只做状态答复，不会重复派发任务。"
        )
    route = _action_display_name(str(context.routing.get("resolved_action") or "brain_next"))
    return f"当前 Run 状态是 {context.current_status}；没有检测到活动任务。下一步路由是 {route}。"


def _output_diagnostic_answer(context: ActionContext) -> str:
    diagnostics = context.diagnostics or {}
    diagnosis = diagnostics.get("outputs") if isinstance(diagnostics.get("outputs"), dict) else diagnostics
    return render_output_diagnostic_answer(
        diagnosis if isinstance(diagnosis, dict) else {},
        current_status=context.current_status,
        active_tasks=context.active_tasks,
    )


def _tool_diagnosis(context: ActionContext) -> dict[str, Any]:
    diagnostics = context.diagnostics or {}
    tool_name = str((context.routing.get("control_tool") or {}).get("tool_name") or "")
    value = diagnostics.get(tool_name)
    return value if isinstance(value, dict) else {}


def _deferred_answer(context: ActionContext) -> str:
    active_count = int(context.active_tasks.get("count") or 0)
    route = _action_display_name(str(context.routing.get("resolved_action") or "brain_next"))
    return (
        f"已接收你的指令，路由到 {route}。"
        f"当前有 {active_count} 个任务正在执行：{_active_tasks_sentence(context.active_tasks)}。"
        "为避免重复派发、覆盖产物或造成资产不一致，本次指令已暂存，等待当前任务结束后再继续处理。"
    )


def _action_display_name(action: str) -> str:
    labels = {
        "brain_next": "下一步",
        "status_query": "状态检查",
        "generate_story_plan": "剧本和分镜",
        "plan_visual_assets": "参考图和视觉资产",
        "generate_keyframes": "关键帧生成",
        "generate_videos": "视频生成",
        "plan_final_edit": "剪辑成片",
    }
    return labels.get(str(action or "").strip(), "下一步")


def _active_tasks_sentence(active_tasks: dict[str, Any]) -> str:
    items = active_tasks.get("items")
    if isinstance(items, list) and items:
        return "；".join(_active_task_label(item) for item in items[:3])

    statuses = ", ".join(str(item) for item in active_tasks.get("statuses") or [])
    task_ids = ", ".join(str(item) for item in active_tasks.get("task_ids") or [])
    if task_ids:
        return f"状态 {statuses or 'unknown'}，任务 {task_ids}"
    return f"状态 {statuses or 'unknown'}"


def _active_task_label(task: Any) -> str:
    if not isinstance(task, dict):
        return str(task)

    task_type = str(task.get("task_type") or "task").strip()
    parts = [_task_type_name(task_type)]

    shot_index = task.get("shot_index")
    if shot_index not in (None, ""):
        parts.append(f"第 {shot_index} 镜")

    provider = str(task.get("provider") or "").strip()
    if provider:
        parts.append(f"provider {provider}")

    status = str(task.get("status") or "").strip()
    if status:
        parts.append(f"状态 {status}")

    progress = task.get("progress")
    if progress not in (None, ""):
        parts.append(f"进度 {progress}%")

    stage = str(task.get("stage_text") or "").strip()
    if stage:
        parts.append(f"阶段：{stage}")

    task_id = str(task.get("task_id") or "").strip()
    if task_id:
        parts.append(f"任务 {task_id}")

    return "，".join(parts)


def _task_type_name(task_type: str) -> str:
    labels = {
        "video_gen": "视频生成",
        "image_gen": "图片/关键帧生成",
        "director_ref_images": "参考图生成",
        "director_script": "剧本/分镜生成",
        "director_prepare_shots": "分镜准备",
        "director_plan_edit": "剪辑规划",
        "director_export_preview": "预览导出",
        "director_export_final": "成片导出",
        "video_production_run": "生产流水线",
    }
    return labels.get(task_type, task_type or "任务")
