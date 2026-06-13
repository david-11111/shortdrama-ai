from __future__ import annotations

import asyncio
import json
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings


AGENT_PHASES = [
    ("read_context", "读取上下文"),
    ("merge_memory", "合并记忆与账本"),
    ("map_techniques", "映射创作技巧"),
    ("check_continuity", "检查剧情承接"),
    ("cost_guard", "成本与风控"),
    ("delivery_audit", "成片可交付检查"),
    ("dispatch_instruction", "发布执行指令"),
    ("writeback_review", "回写与复盘"),
]

RUN_STATES = {
    "created",
    "analyzing",
    "planning",
    "waiting_approval",
    "dispatching",
    "queued",
    "running",
    "verifying",
    "writing_back",
    "completed",
    "blocked",
    "failed",
    "cancelled",
}

TASK_AGENT_STATES = {
    "queued",
    "worker_started",
    "provider_requesting",
    "provider_waiting",
    "downloading",
    "uploading",
    "writing_back",
    "done",
    "failed",
    "refunded",
}

AGENT_EVENT_ACTORS = {
    "deepseek",
    "doubao",
    "seedream",
    "seedance",
    "kling",
    "ffmpeg",
    "brain",
    "executor",
    "state_machine",
    "guardrail",
    "ledger",
    "memory",
    "user",
    "system",
}
AGENT_EVENT_KINDS = {
    "narration",
    "decision",
    "dispatch",
    "deferred",
    "blocked",
    "risk",
    "tool_call",
    "tool_result",
    "artifact",
    "writeback",
    "audit",
    "guardrail",
    "recovery",
    "error",
}
AGENT_EVENT_VISIBILITIES = {"user", "expert", "debug"}

_SOURCE_ACTOR_ALIASES = {
    "api": "executor",
    "queue": "executor",
    "worker": "executor",
    "ledger": "ledger",
    "memory": "memory",
    "provider": "system",
}

_EVENT_KIND_ALIASES = {
    "trace": "narration",
    "risk": "guardrail",
    "writeback": "tool_result",
}


async def create_agent_run(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    trigger_type: str = "user_click",
    goal: str = "",
    mode: str = "step",
    estimated_max_credits: int = 0,
    allowed_max_credits: int = 0,
    production_ledger: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> str:
    payload = {**(meta or {}), "mode": normalize_run_mode(mode)}
    allowed = max(0, int(allowed_max_credits or estimated_max_credits or 0))
    result = await db.execute(
        text(
            """
            INSERT INTO agent_runs (
                project_id, user_id, trigger_type, goal, status,
                current_phase, mode, estimated_max_credits, allowed_max_credits,
                remaining_run_budget, production_ledger, summary, meta
            )
            VALUES (
                :project_id, :user_id, :trigger_type, :goal, 'created',
                'created', :mode, :estimated_max_credits, :allowed_max_credits,
                :remaining_run_budget, CAST(:production_ledger AS JSONB), :summary, CAST(:meta AS JSONB)
            )
            RETURNING id
            """
        ),
        {
            "project_id": project_id,
            "user_id": user_id,
            "trigger_type": trigger_type,
            "goal": goal,
            "summary": f"Agent run started in {payload['mode']} mode.",
            "mode": payload["mode"],
            "estimated_max_credits": max(0, int(estimated_max_credits or 0)),
            "allowed_max_credits": allowed,
            "remaining_run_budget": allowed,
            "production_ledger": json.dumps(production_ledger or {}, ensure_ascii=False, default=str),
            "meta": json.dumps(payload, ensure_ascii=False, default=str),
        },
    )
    run_id = str(result.scalar_one())
    await publish_agent_event(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        source="brain",
        event_type="trace",
        phase="created",
        title="创建 Agent Run",
        detail=f"mode={payload['mode']}；goal={goal or '继续推进项目'}",
        status="created",
        progress=1,
        meta={
            **payload,
            "budget": {
                "estimated_max_credits": max(0, int(estimated_max_credits or 0)),
                "allowed_max_credits": allowed,
                "reserved_credits": 0,
                "spent_credits": 0,
                "remaining_run_budget": allowed,
            },
            "production_ledger": production_ledger or {},
        },
    )
    return run_id


def normalize_run_mode(mode: str | None) -> str:
    value = str(mode or "step").strip().lower()
    if value in {"preview", "step", "autopilot"}:
        return value
    return "step"


async def create_agent_step(
    db: AsyncSession,
    *,
    run_id: str,
    step_index: int,
    phase: str,
    title: str,
    status: str = "running",
    input_summary: str = "",
    decision_summary: str = "",
    output_summary: str = "",
    stop_reason: str = "",
    meta: dict[str, Any] | None = None,
) -> str:
    result = await db.execute(
        text(
            """
            INSERT INTO agent_steps (
                run_id, step_index, phase, title, status,
                input_summary, decision_summary, output_summary, stop_reason, meta
            )
            VALUES (
                CAST(:run_id AS UUID), :step_index, :phase, :title, :status,
                :input_summary, :decision_summary, :output_summary, :stop_reason,
                CAST(:meta AS JSONB)
            )
            ON CONFLICT (run_id, step_index)
            DO UPDATE SET
                phase = EXCLUDED.phase,
                title = EXCLUDED.title,
                status = EXCLUDED.status,
                input_summary = EXCLUDED.input_summary,
                decision_summary = EXCLUDED.decision_summary,
                output_summary = EXCLUDED.output_summary,
                stop_reason = EXCLUDED.stop_reason,
                meta = EXCLUDED.meta,
                updated_at = NOW(),
                ended_at = CASE WHEN EXCLUDED.status IN ('done','failed','blocked') THEN NOW() ELSE agent_steps.ended_at END
            RETURNING id
            """
        ),
        {
            "run_id": run_id,
            "step_index": step_index,
            "phase": phase,
            "title": title,
            "status": status,
            "input_summary": input_summary,
            "decision_summary": decision_summary,
            "output_summary": output_summary,
            "stop_reason": stop_reason,
            "meta": json.dumps(meta or {}, ensure_ascii=False, default=str),
        },
    )
    return str(result.scalar_one())


async def update_agent_run(
    db: AsyncSession,
    *,
    run_id: str,
    status: str | None = None,
    current_phase: str | None = None,
    summary: str | None = None,
    final_decision: str | None = None,
    reserved_credits_delta: int | None = None,
    spent_credits_delta: int | None = None,
    meta_updates: dict[str, Any] | None = None,
) -> None:
    updates = []
    params: dict[str, Any] = {"run_id": run_id}
    if meta_updates:
        updates.append("meta = COALESCE(meta, '{}'::JSONB) || CAST(:meta_updates AS JSONB)")
        params["meta_updates"] = json.dumps(meta_updates, ensure_ascii=False, default=str)
    if status is not None:
        status = normalize_run_state(status)
        updates.append("status = :status")
        params["status"] = status
    if current_phase is not None:
        updates.append("current_phase = :current_phase")
        params["current_phase"] = current_phase
    if summary is not None:
        updates.append("summary = :summary")
        params["summary"] = summary
    if final_decision is not None:
        updates.append("final_decision = :final_decision")
        params["final_decision"] = final_decision
    if reserved_credits_delta is not None:
        updates.append("reserved_credits = GREATEST(0, reserved_credits + :reserved_credits_delta)")
        updates.append("remaining_run_budget = GREATEST(0, remaining_run_budget - :reserved_credits_delta)")
        params["reserved_credits_delta"] = int(reserved_credits_delta)
    if spent_credits_delta is not None:
        updates.append("spent_credits = GREATEST(0, spent_credits + :spent_credits_delta)")
        params["spent_credits_delta"] = int(spent_credits_delta)
    if status in {"completed", "failed", "blocked", "cancelled"}:
        updates.append("ended_at = NOW()")
    updates.append("updated_at = NOW()")
    await db.execute(
        text(f"UPDATE agent_runs SET {', '.join(updates)} WHERE id = CAST(:run_id AS UUID)"),
        params,
    )


def normalize_run_state(status: str | None) -> str:
    value = str(status or "running").strip().lower()
    if value == "done":
        return "completed"
    if value in RUN_STATES:
        return value
    return "running"


def normalize_task_agent_state(status: str | None) -> str:
    value = str(status or "queued").strip().lower()
    if value in {"running", "started"}:
        return "worker_started"
    if value == "complete":
        return "done"
    if value in TASK_AGENT_STATES:
        return value
    return "queued"


async def ensure_run_budget(
    db: AsyncSession,
    *,
    run_id: str | None,
    project_id: str,
    user_id: int,
    next_cost: int,
    label: str,
) -> bool:
    if not run_id:
        return True
    result = await db.execute(
        text(
            """
            SELECT remaining_run_budget, allowed_max_credits
            FROM agent_runs
            WHERE id = CAST(:run_id AS UUID) AND project_id = :project_id AND user_id = :user_id
            FOR UPDATE
            """
        ),
        {"run_id": run_id, "project_id": project_id, "user_id": user_id},
    )
    row = result.fetchone()
    if not row:
        return True
    remaining = int(row.remaining_run_budget or 0)
    allowed = int(row.allowed_max_credits or 0)
    if allowed <= 0:
        return True
    if int(next_cost or 0) <= remaining:
        return True
    await update_agent_run(
        db,
        run_id=run_id,
        status="blocked",
        current_phase="cost_guard",
        final_decision=f"Blocked by run budget: {label}",
    )
    await publish_agent_event(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        source="brain",
        event_type="risk",
        phase="cost_guard",
        title="运行预算阻断",
        detail=f"{label} 需要 {int(next_cost or 0)} 积分，但本次 run 剩余预算 {remaining}。",
        status="blocked",
        progress=100,
        meta={"next_cost": int(next_cost or 0), "remaining_run_budget": remaining, "allowed_max_credits": allowed},
    )
    return False


async def publish_agent_event(
    db: AsyncSession,
    *,
    run_id: str | None,
    project_id: str,
    source: str,
    event_type: str,
    phase: str,
    title: str,
    detail: str,
    status: str = "running",
    progress: int | None = None,
    user_id: int | None = None,
    task_id: str | None = None,
    step_id: str | None = None,
    meta: dict[str, Any] | None = None,
    actor: str | None = None,
    event_kind: str | None = None,
    visibility: str | None = None,
    summary: str | None = None,
    reason: str | None = None,
    artifact_refs: list[Any] | None = None,
    debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta_payload = dict(meta or {})
    agent_event = normalize_agent_event(
        source=source,
        event_type=event_type,
        title=title,
        detail=detail,
        meta=meta_payload,
        actor=actor,
        event_kind=event_kind,
        visibility=visibility,
        summary=summary,
        reason=reason,
        artifact_refs=artifact_refs,
        debug=debug,
    )
    meta_payload["agent_event"] = agent_event
    result = await db.execute(
        text(
            """
            INSERT INTO agent_events (
                run_id, project_id, task_id, step_id, user_id,
                source, event_type, phase, title, detail, status, progress, meta
            )
            VALUES (
                CAST(:run_id AS UUID), :project_id, CAST(:task_id AS UUID),
                CAST(:step_id AS UUID), :user_id, :source, :event_type,
                :phase, :title, :detail, :status, :progress, CAST(:meta AS JSONB)
            )
            RETURNING id, created_at
            """
        ),
        {
            "run_id": run_id or None,
            "project_id": project_id,
            "task_id": task_id or None,
            "step_id": step_id or None,
            "user_id": user_id,
            "source": source,
            "event_type": event_type,
            "phase": phase,
            "title": title,
            "detail": detail,
            "status": status,
            "progress": progress,
            "meta": json.dumps(meta_payload, ensure_ascii=False, default=str),
        },
    )
    row = result.fetchone()
    payload = {
        "type": "execution_event",
        "id": str(row.id),
        "run_id": run_id,
        "project_id": project_id,
        "task_id": task_id,
        "step_id": step_id,
        "user_id": user_id,
        "source": source,
        "event_type": event_type,
        "phase": phase,
        "title": title,
        "detail": detail,
        "status": status,
        "progress": progress,
        "meta": meta_payload,
        **agent_event,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    await _publish_project_event(project_id, payload)
    return payload


def normalize_agent_event(
    *,
    source: str | None,
    event_type: str | None,
    title: str | None,
    detail: str | None,
    meta: dict[str, Any] | None = None,
    actor: str | None = None,
    event_kind: str | None = None,
    visibility: str | None = None,
    summary: str | None = None,
    reason: str | None = None,
    artifact_refs: list[Any] | None = None,
    debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = meta if isinstance(meta, dict) else {}
    stored = meta.get("agent_event") if isinstance(meta.get("agent_event"), dict) else {}
    normalized_actor = _normalize_agent_actor(actor or stored.get("actor") or source)
    normalized_kind = _normalize_agent_event_kind(event_kind or stored.get("event_kind") or event_type)
    normalized_visibility = _normalize_agent_visibility(visibility or stored.get("visibility"))
    normalized_summary = _first_text(summary, stored.get("summary"), title, detail, default="Agent event")
    normalized_reason = _first_text(reason, stored.get("reason"), detail, default="")
    refs = artifact_refs if artifact_refs is not None else stored.get("artifact_refs")
    debug_payload = debug if debug is not None else stored.get("debug")
    return {
        "actor": normalized_actor,
        "event_kind": normalized_kind,
        "visibility": normalized_visibility,
        "summary": normalized_summary,
        "reason": normalized_reason,
        "artifact_refs": refs if isinstance(refs, list) else [],
        "debug": debug_payload if isinstance(debug_payload, dict) else {},
    }


def _normalize_agent_actor(value: Any) -> str:
    raw = str(value or "").strip().lower()
    actor = _SOURCE_ACTOR_ALIASES.get(raw, raw)
    return actor if actor in AGENT_EVENT_ACTORS else "system"


def _normalize_agent_event_kind(value: Any) -> str:
    raw = str(value or "").strip().lower()
    kind = _EVENT_KIND_ALIASES.get(raw, raw)
    return kind if kind in AGENT_EVENT_KINDS else "narration"


def _normalize_agent_visibility(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in AGENT_EVENT_VISIBILITIES else "user"


def _first_text(*values: Any, default: str) -> str:
    for value in values:
        text_value = str(value or "").strip()
        if text_value:
            return text_value[:500]
    return default


async def record_agent_artifact(
    db: AsyncSession,
    *,
    run_id: str | None,
    project_id: str,
    artifact_type: str,
    uri: str = "",
    summary: str = "",
    user_id: int | None = None,
    task_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO agent_artifacts (
                run_id, project_id, task_id, user_id, artifact_type, uri, summary, meta
            )
            VALUES (
                CAST(:run_id AS UUID), :project_id, CAST(:task_id AS UUID), :user_id,
                :artifact_type, :uri, :summary, CAST(:meta AS JSONB)
            )
            """
        ),
        {
            "run_id": run_id or None,
            "project_id": project_id,
            "task_id": task_id or None,
            "user_id": user_id,
            "artifact_type": artifact_type,
            "uri": uri,
            "summary": summary,
            "meta": json.dumps(meta or {}, ensure_ascii=False, default=str),
        },
    )
    await publish_agent_event(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        task_id=task_id,
        source="ledger",
        event_type="artifact",
        phase="artifact_recorded",
        title=f"记录产物：{artifact_type}",
        detail=summary or uri or artifact_type,
        status="done",
        progress=None,
        meta={"artifact_type": artifact_type, "uri": uri, **(meta or {})},
    )


async def list_project_agent_events(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    limit: int = 100,
    run_id: str | None = None,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    filters = [
        "e.project_id = :project_id",
        "(e.user_id = :user_id OR r.user_id = :user_id)",
    ]
    params: dict[str, Any] = {
        "project_id": project_id,
        "user_id": user_id,
        "limit": max(1, min(limit, 300)),
    }
    if run_id:
        filters.append("e.run_id = CAST(:run_id AS UUID)")
        params["run_id"] = run_id
    if event_type:
        filters.append("e.event_type = :event_type")
        params["event_type"] = event_type
    result = await db.execute(
        text(
            f"""
            SELECT e.*
            FROM agent_events e
            LEFT JOIN agent_runs r ON r.id = e.run_id
            WHERE {' AND '.join(filters)}
            ORDER BY e.created_at DESC
            LIMIT :limit
            """
        ),
        params,
    )
    return [_event_row_to_dict(row) for row in result.mappings().all()]


async def list_project_agent_runs(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT
                r.id,
                r.project_id,
                r.user_id,
                r.trigger_type,
                r.goal,
                r.status,
                r.current_phase,
                r.mode,
                r.started_at,
                r.ended_at,
                r.summary,
                r.final_decision,
                COUNT(e.id) AS event_count
            FROM agent_runs r
            LEFT JOIN agent_events e ON e.run_id = r.id
            WHERE r.project_id = :project_id AND r.user_id = :user_id
            GROUP BY r.id
            ORDER BY r.started_at DESC
            LIMIT :limit
            """
        ),
        {"project_id": project_id, "user_id": user_id, "limit": max(1, min(limit, 100))},
    )
    return [_run_row_to_dict(row) for row in result.mappings().all()]


async def emit_brain_snapshot_steps(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    brain: dict[str, Any],
    mode: str,
) -> None:
    context = brain.get("context") if isinstance(brain.get("context"), dict) else {}
    step_specs = [
        (
            "read_context",
            "读取上下文",
            _summarize_context(context.get("context_coverage") or brain.get("read_files")),
            "识别项目文件、分镜、记忆和约束是否可用。",
            f"phase={brain.get('phase') or '-'}",
            "",
            "trace",
        ),
        (
            "merge_memory",
            "合并记忆与账本",
            _coverage_summary(context.get("ledger_merge_audit")),
            "把 workspace、shot_rows、final_edit_plan 合并成生产账本。",
            _first_gap(context.get("ledger_merge_audit")) or "账本已进入判断。",
            "",
            "decision",
        ),
        (
            "map_techniques",
            "映射创作技巧",
            _coverage_summary(context.get("creative_lowering_audit")),
            "检查镜头运动、光影、情绪、配音、剪辑技巧是否下沉到可执行字段。",
            _first_gap(context.get("creative_lowering_audit")) or "创作技巧已形成执行边界。",
            "",
            "decision",
        ),
        (
            "check_continuity",
            "检查剧情承接",
            _coverage_summary(context.get("continuity_handoff_audit")),
            "确认第几场、第几分钟、前后场承接。",
            _first_gap(context.get("continuity_handoff_audit")) or "剧情承接进入下一步判断。",
            "",
            "decision",
        ),
        (
            "cost_guard",
            "成本与风控",
            _coverage_summary(context.get("cost_control_audit")),
            "检查小步推进、资产复用、积分、限流和并发闸门。",
            _first_gap(context.get("cost_control_audit")) or "风控允许在当前模式下继续。",
            "",
            "risk" if _has_gap(context.get("cost_control_audit")) else "decision",
        ),
        (
            "delivery_audit",
            "成片可交付检查",
            _coverage_summary(context.get("final_delivery_audit")),
            "检查视频、BGM、字幕、配音、剪辑方案是否齐全。",
            _first_gap(context.get("final_delivery_audit")) or "交付检查已完成。",
            "",
            "risk" if _has_gap(context.get("final_delivery_audit")) else "decision",
        ),
        (
            "dispatch_instruction",
            "发布执行指令",
            f"next_action={brain.get('next_action') or '-'}；can_continue={bool(brain.get('can_continue'))}；mode={mode}",
            "根据大脑快照选择 preview/step/autopilot 的执行边界。",
            brain.get("summary") or "",
            "Preview 模式只分析不派发；Step 模式只推进一步；Autopilot 需要预算和审批闸门。",
            "tool_call" if brain.get("can_continue") and mode != "preview" else "decision",
        ),
        (
            "writeback_review",
            "回写与复盘",
            _coverage_summary(context.get("feedback_loop_audit")),
            "检查决策、媒体结果、失败和剪辑方案是否会被下一轮读取。",
            _first_gap(context.get("feedback_loop_audit")) or "回写链路可供下一轮大脑继承。",
            "",
            "decision",
        ),
    ]
    for index, (phase, title, input_summary, decision, output, stop, event_type) in enumerate(step_specs, 1):
        step_id = await create_agent_step(
            db,
            run_id=run_id,
            step_index=index,
            phase=phase,
            title=title,
            status="done",
            input_summary=input_summary,
            decision_summary=decision,
            output_summary=output,
            stop_reason=stop,
            meta={"mode": mode},
        )
        await update_agent_run(db, run_id=run_id, current_phase=phase)
        await publish_agent_event(
            db,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            step_id=step_id,
            source="brain",
            event_type=event_type,
            phase=phase,
            title=title,
            detail=f"{input_summary}；{decision}；{output}".strip("；"),
            status="done",
            progress=min(95, index * 10),
            meta={"input": input_summary, "decision": decision, "output": output, "stop": stop},
        )


def _event_row_to_dict(row: Any) -> dict[str, Any]:
    meta = row.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    agent_event = normalize_agent_event(
        source=row["source"],
        event_type=row["event_type"],
        title=row["title"],
        detail=row["detail"],
        meta=meta,
    )
    return {
        "type": "execution_event",
        "id": str(row["id"]),
        "run_id": str(row["run_id"]) if row.get("run_id") else None,
        "project_id": row["project_id"],
        "task_id": str(row["task_id"]) if row.get("task_id") else None,
        "step_id": str(row["step_id"]) if row.get("step_id") else None,
        "user_id": row.get("user_id"),
        "source": row["source"],
        "event_type": row["event_type"],
        "phase": row["phase"],
        "title": row["title"],
        "detail": row["detail"],
        "status": row["status"],
        "progress": row.get("progress"),
        "meta": meta,
        **agent_event,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def _run_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "run_id": str(row["id"]),
        "project_id": row["project_id"],
        "user_id": row.get("user_id"),
        "trigger_type": row.get("trigger_type"),
        "goal": row.get("goal"),
        "status": row.get("status"),
        "current_phase": row.get("current_phase"),
        "mode": row.get("mode"),
        "started_at": row["started_at"].isoformat() if row.get("started_at") else None,
        "finished_at": row["ended_at"].isoformat() if row.get("ended_at") else None,
        "summary": row.get("summary"),
        "final_decision": row.get("final_decision"),
        "event_count": int(row.get("event_count") or 0),
    }


def _coverage_summary(rows: Any) -> str:
    if not isinstance(rows, list) or not rows:
        return "等待审计数据"
    covered = sum(1 for item in rows if isinstance(item, dict) and item.get("coverage") == "covered")
    partial = sum(1 for item in rows if isinstance(item, dict) and item.get("coverage") == "partial")
    missing = sum(1 for item in rows if isinstance(item, dict) and item.get("coverage") == "missing")
    return f"covered={covered}；partial={partial}；missing={missing}；total={len(rows)}"


def _summarize_context(rows: Any) -> str:
    if not isinstance(rows, list) or not rows:
        return "未读取到上下文清单"
    ready = sum(1 for item in rows if isinstance(item, dict) and item.get("exists"))
    consumed = sum(1 for item in rows if isinstance(item, dict) and item.get("consumed"))
    return f"files={ready}/{len(rows)}；consumed={consumed}"


def _first_gap(rows: Any) -> str:
    if not isinstance(rows, list):
        return ""
    for item in rows:
        if isinstance(item, dict) and item.get("coverage") != "covered":
            return str(item.get("gap") or item.get("label") or item.get("component") or "")
    return ""


def _has_gap(rows: Any) -> bool:
    return bool(_first_gap(rows))


async def _publish_project_event(project_id: str, payload: dict[str, Any]) -> None:
    try:
        async with aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True) as client:
            await client.publish(f"project:{project_id}:events", json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:
        # Observability must not break production execution.
        return


def publish_project_event_sync(project_id: str, payload: dict[str, Any]) -> None:
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_publish_project_event(project_id, payload))
        else:
            loop.create_task(_publish_project_event(project_id, payload))
    except Exception:
        return
