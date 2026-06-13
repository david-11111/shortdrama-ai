from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_runtime import publish_agent_event
from app.services.agent_runtime_contracts import RuntimeFeedback


def feedback_event_payload(
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    feedback: RuntimeFeedback,
) -> dict[str, Any]:
    feedback_payload = feedback.as_dict()
    return {
        "run_id": run_id,
        "project_id": project_id,
        "user_id": user_id,
        "source": "main_chain",
        "event_type": "feedback",
        "phase": str(feedback.status),
        "title": feedback.summary[:120],
        "detail": feedback.next_step or feedback.summary,
        "status": feedback.status,
        "progress": feedback.progress.get("percentage") if isinstance(feedback.progress, dict) else None,
        "meta": {"feedback": feedback_payload},
        "event_kind": "narration",
        "visibility": feedback_payload["audience"],
        "summary": feedback.summary,
        "reason": feedback.next_step,
    }


async def publish_runtime_feedback(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    feedback: RuntimeFeedback,
) -> dict[str, Any]:
    return await publish_agent_event(
        db,
        **feedback_event_payload(run_id=run_id, project_id=project_id, user_id=user_id, feedback=feedback),
    )
