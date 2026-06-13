from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


SOURCE = "decision_mailbox"


async def submit_decision(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    packet: dict[str, Any],
    parent_decision_id: str = "",
    decision_rationale: str = "",
    thinking_artifacts: list[dict[str, Any]] | None = None,
) -> str:
    mission = packet.get("mission") if isinstance(packet.get("mission"), dict) else {}
    decision_id = str(mission.get("mission_id") or mission.get("idempotency_key") or packet.get("action") or "")
    mailbox = {
        "status": "pending",
        "decision_id": decision_id,
        "packet": packet,
        "parent_decision_id": parent_decision_id,
        "idempotency_key": str(mission.get("idempotency_key") or ""),
        "decision_rationale": decision_rationale,
        "thinking_artifacts": list(thinking_artifacts or []),
    }
    return await _insert_mailbox_event(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        status="pending",
        title="Decision queued",
        detail=str(packet.get("action") or "decision"),
        mailbox=mailbox,
    )


async def complete_decision(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    decision_id: str,
    result_ref: dict[str, Any],
) -> str:
    return await _insert_mailbox_event(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        status="completed",
        title="Decision completed",
        detail=decision_id,
        mailbox={"status": "completed", "decision_id": decision_id, "result_ref": result_ref},
    )


async def mark_decision_rejected(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    decision_id: str,
    reason: str,
) -> str:
    return await _insert_mailbox_event(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        status="rejected",
        title="Decision rejected",
        detail=reason,
        mailbox={"status": "rejected", "decision_id": decision_id, "reason": reason},
    )


async def _insert_mailbox_event(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    status: str,
    title: str,
    detail: str,
    mailbox: dict[str, Any],
) -> str:
    result = await db.execute(
        text(
            """
            INSERT INTO agent_events (
                run_id, project_id, user_id, source, event_type, phase,
                title, detail, status, progress, meta
            )
            VALUES (
                CAST(:run_id AS UUID), :project_id, :user_id, :source,
                'decision_mailbox', :phase, :title, :detail, :status, NULL,
                CAST(:meta AS JSONB)
            )
            RETURNING id
            """
        ),
        {
            "run_id": run_id,
            "project_id": project_id,
            "user_id": user_id,
            "source": SOURCE,
            "phase": status,
            "title": title,
            "detail": detail,
            "status": status,
            "meta": json.dumps({"mailbox": mailbox}, ensure_ascii=False, default=str),
        },
    )
    return str(result.scalar_one())
