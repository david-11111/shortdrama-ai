from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import bindparam, text

from app.db import AsyncSessionLocal
from app.services.agent_runtime import publish_agent_event


LOGGER = logging.getLogger(__name__)

ACTIVE_TASK_STATUSES = (
    "pending",
    "queued",
    "retrying",
    "running",
    "worker_started",
    "provider_requesting",
    "provider_waiting",
    "downloading",
    "uploading",
    "writing_back",
)


async def drain_pending_instruction_after_task(task_id: str) -> None:
    """Dispatch the oldest deferred human instruction once a run has no active tasks."""
    async with AsyncSessionLocal() as db:
        task = await _task_context(db, task_id)
        if not task or not task.get("run_id"):
            return

        run_id = str(task["run_id"])
        project_id = str(task["project_id"])
        user_id = int(task["user_id"])
        if await _has_active_tasks(db, run_id=run_id, user_id=user_id):
            return

        pending = await _claim_next_pending_instruction(db, run_id=run_id, user_id=user_id)
        if not pending:
            return

        event_id = str(pending["id"])
        meta = pending["meta"] if isinstance(pending["meta"], dict) else {}
        pending_instruction = meta.get("pending_instruction") if isinstance(meta.get("pending_instruction"), dict) else {}
        continue_body = pending_instruction.get("continue_body") if isinstance(pending_instruction.get("continue_body"), dict) else {}
        routing = pending_instruction.get("routing") if isinstance(pending_instruction.get("routing"), dict) else {}
        instruction = str(pending_instruction.get("instruction") or routing.get("instruction") or "")
        action = str(routing.get("resolved_action") or continue_body.get("action") or "brain_next")

        await publish_agent_event(
            db,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            source="api",
            event_type="decision",
            phase="pending_instruction_dispatch",
            title="暂存指令开始执行",
            detail=f"route={action}；instruction={instruction}",
            status="running",
            progress=76,
            meta={"claimed_event_id": event_id, "routing": routing},
        )
        await db.commit()

        try:
            from app.routes.workbench import continue_project_brain

            result = await continue_project_brain(
                project_id=project_id,
                body=continue_body,
                db=db,
                current_user={"id": user_id},
            )
            await _mark_pending_instruction(db, event_id=event_id, status="dispatched", result=result)
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source="api",
                event_type="tool_result",
                phase="pending_instruction_dispatched",
                title="暂存指令已派发",
                detail=f"route={action}；status={result.get('status')}",
                status="done",
                progress=78,
                meta={"claimed_event_id": event_id, "routing": routing, "result": result},
            )
            await db.commit()
        except Exception as exc:
            LOGGER.exception("Pending instruction dispatch failed run_id=%s event_id=%s", run_id, event_id)
            await _mark_pending_instruction(db, event_id=event_id, status="failed", result={"error": str(exc)})
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source="api",
                event_type="error",
                phase="pending_instruction_failed",
                title="暂存指令派发失败",
                detail=str(exc),
                status="failed",
                progress=78,
                meta={"claimed_event_id": event_id, "routing": routing, "error": str(exc)},
            )
            await db.commit()


async def _task_context(db: Any, task_id: str) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                """
                SELECT task_id, project_id, run_id, user_id
                FROM tasks
                WHERE task_id = CAST(:task_id AS UUID)
                LIMIT 1
                """
            ),
            {"task_id": task_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def _has_active_tasks(db: Any, *, run_id: str, user_id: int) -> bool:
    query = text(
        """
        SELECT 1
        FROM tasks
        WHERE run_id = CAST(:run_id AS UUID)
          AND user_id = :user_id
          AND status IN :active_statuses
        LIMIT 1
        """
    ).bindparams(bindparam("active_statuses", expanding=True))
    return (
        await db.execute(query, {"run_id": run_id, "user_id": user_id, "active_statuses": ACTIVE_TASK_STATUSES})
    ).scalar_one_or_none() is not None


async def _claim_next_pending_instruction(db: Any, *, run_id: str, user_id: int) -> dict[str, Any] | None:
    row = (
        await db.execute(
            text(
                """
                SELECT id::text AS id, meta
                FROM agent_events
                WHERE run_id = CAST(:run_id AS UUID)
                  AND user_id = :user_id
                  AND phase = 'human_response'
                  AND status = 'deferred'
                  AND meta->'pending_instruction'->>'status' = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"run_id": run_id, "user_id": user_id},
        )
    ).mappings().first()
    if not row:
        return None
    meta = row["meta"] if isinstance(row["meta"], dict) else {}
    pending = meta.get("pending_instruction") if isinstance(meta.get("pending_instruction"), dict) else {}
    meta["pending_instruction"] = {**pending, "status": "dispatching"}
    await db.execute(
        text("UPDATE agent_events SET meta = CAST(:meta AS JSONB) WHERE id = CAST(:event_id AS UUID)"),
        {"event_id": str(row["id"]), "meta": json.dumps(meta, ensure_ascii=False, default=str)},
    )
    await db.commit()
    return {"id": str(row["id"]), "meta": meta}


async def _mark_pending_instruction(db: Any, *, event_id: str, status: str, result: dict[str, Any]) -> None:
    row = (
        await db.execute(
            text("SELECT meta FROM agent_events WHERE id = CAST(:event_id AS UUID) LIMIT 1"),
            {"event_id": event_id},
        )
    ).mappings().first()
    meta = row["meta"] if row and isinstance(row["meta"], dict) else {}
    pending = meta.get("pending_instruction") if isinstance(meta.get("pending_instruction"), dict) else {}
    meta["pending_instruction"] = {**pending, "status": status, "result": result}
    await db.execute(
        text("UPDATE agent_events SET meta = CAST(:meta AS JSONB) WHERE id = CAST(:event_id AS UUID)"),
        {"event_id": event_id, "meta": json.dumps(meta, ensure_ascii=False, default=str)},
    )
