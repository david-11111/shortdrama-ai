from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.routes.workbench import _dispatch_action_after_planning
from app.services.agent_run_state_machine import evaluate_action_gate
from app.services.project_brain import build_project_brain


ACTIVE_STATUSES = {
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
}


async def diagnose(run_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        run = await _one(
            session,
            """
            SELECT id::text AS run_id, project_id, user_id, status, current_phase,
                   goal, summary, final_decision, mode, started_at, ended_at
            FROM agent_runs
            WHERE id = CAST(:run_id AS UUID)
            """,
            {"run_id": run_id},
        )
        if not run:
            return {"run_id": run_id, "found": False, "why_not_dispatched": "agent_run_not_found"}

        project_id = str(run["project_id"])
        user_id = int(run["user_id"])
        shots = await _all(
            session,
            """
            SELECT shot_index, prompt, duration, status, selected_image, selected_video, last_error
            FROM shot_rows
            WHERE project_id = :project_id AND user_id = :user_id
            ORDER BY shot_index ASC
            """,
            {"project_id": project_id, "user_id": user_id},
        )
        tasks = await _all(
            session,
            """
            SELECT task_id::text AS task_id, task_type, status, progress,
                   payload, error_message, created_at, updated_at
            FROM tasks
            WHERE run_id = CAST(:run_id AS UUID) AND user_id = :user_id
            ORDER BY created_at ASC
            """,
            {"run_id": run_id, "user_id": user_id},
        )
        recent_events = await _all(
            session,
            """
            SELECT event_type, phase, title, detail, status, actor, event_kind,
                   visibility, summary, reason, created_at
            FROM project_agent_events
            WHERE run_id = CAST(:run_id AS UUID) AND user_id = :user_id
            ORDER BY created_at DESC
            LIMIT 12
            """,
            {"run_id": run_id, "user_id": user_id},
        )

    brain = build_project_brain(project_id, operational_shots=shots)
    next_action = str(brain.get("next_action") or "")
    dispatch_action = _dispatch_action_after_planning(brain, next_action)
    gate_action = dispatch_action or next_action or "generate_keyframes"
    gate = evaluate_action_gate(gate_action, shots=shots, tasks=tasks)

    image_tasks = [task for task in tasks if task.get("task_type") == "image_gen"]
    video_tasks = [task for task in tasks if task.get("task_type") == "video_gen"]
    active_tasks = [task for task in tasks if str(task.get("status") or "") in ACTIVE_STATUSES]
    pending_keyframes = [shot for shot in shots if shot.get("prompt") and not shot.get("selected_image")]
    eligible_keyframes = [
        shot for shot in pending_keyframes
        if str(shot.get("status") or "") not in {"generating_image", "generating_video", "video_done"}
    ]

    why = _why_not_dispatched(
        run=run,
        shots=shots,
        image_tasks=image_tasks,
        active_tasks=active_tasks,
        pending_keyframes=pending_keyframes,
        eligible_keyframes=eligible_keyframes,
        next_action=next_action,
        dispatch_action=dispatch_action,
        gate=gate,
    )

    return {
        "run_id": run_id,
        "found": True,
        "run": _compact_run(run),
        "project_id": project_id,
        "shot_count": len(shots),
        "selected_image_count": sum(1 for shot in shots if shot.get("selected_image")),
        "selected_video_count": sum(1 for shot in shots if shot.get("selected_video")),
        "pending_keyframe_count": len(pending_keyframes),
        "eligible_keyframe_count": len(eligible_keyframes),
        "task_count": len(tasks),
        "active_task_count": len(active_tasks),
        "image_gen_task_count": len(image_tasks),
        "video_gen_task_count": len(video_tasks),
        "brain_next_action": next_action,
        "dispatch_action_after_planning": dispatch_action,
        "gate": gate,
        "why_not_dispatched": why,
        "recommended_fix": _recommended_fix(why),
        "recent_events": [_compact_event(event) for event in recent_events],
        "task_statuses": _counts(tasks, "status"),
        "image_task_statuses": _counts(image_tasks, "status"),
    }


def _why_not_dispatched(
    *,
    run: dict[str, Any],
    shots: list[dict[str, Any]],
    image_tasks: list[dict[str, Any]],
    active_tasks: list[dict[str, Any]],
    pending_keyframes: list[dict[str, Any]],
    eligible_keyframes: list[dict[str, Any]],
    next_action: str,
    dispatch_action: str,
    gate: dict[str, Any],
) -> str:
    if image_tasks:
        return "image_tasks_already_dispatched"
    if active_tasks:
        return "active_tasks_block_dispatch"
    if not shots:
        return "no_shot_rows"
    if not pending_keyframes:
        return "no_pending_keyframes"
    if not eligible_keyframes:
        return "no_eligible_keyframe_shots"
    if not gate.get("allowed", True):
        return "state_machine_gate_blocked"
    if dispatch_action == "generate_keyframes":
        if str(run.get("status") or "") == "completed":
            return "completed_before_dispatch_likely_old_backend_or_restart_missing"
        return "expected_dispatch_generate_keyframes_check_worker_or_logs"
    if next_action in {"lock_assets", "plan_scene"}:
        return "planning_handoff_missing"
    return "next_action_not_dispatchable"


def _recommended_fix(reason: str) -> str:
    fixes = {
        "image_tasks_already_dispatched": "Wait for image_gen tasks or inspect worker/Celery if they stay queued.",
        "active_tasks_block_dispatch": "Wait for active tasks; do not dispatch duplicate generation.",
        "no_shot_rows": "Run generate_story_plan again; script/storyboard did not write shot_rows.",
        "no_pending_keyframes": "No keyframe generation needed; selected_image already exists or prompts are missing.",
        "no_eligible_keyframe_shots": "Reset stuck shot_rows status or wait for existing generation writeback.",
        "state_machine_gate_blocked": "Read gate.missing and run the recovery action first.",
        "completed_before_dispatch_likely_old_backend_or_restart_missing": "Restart API service so the planning handoff patch is active, then create a new run.",
        "expected_dispatch_generate_keyframes_check_worker_or_logs": "API decided keyframes should dispatch; check workbench _continue_generate_keyframes logs, budget gate, Celery send_task.",
        "planning_handoff_missing": "Backend planning handoff did not map lock_assets/plan_scene to generate_keyframes.",
        "next_action_not_dispatchable": "Add a controlled executor mapping for the next action or keep run waiting for human confirmation.",
    }
    return fixes.get(reason, "Inspect run events and backend logs.")


async def _one(session, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
    result = await session.execute(text(query), params)
    row = result.mappings().first()
    return dict(row) if row else None


async def _all(session, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    result = await session.execute(text(query), params)
    return [dict(row) for row in result.mappings().all()]


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _compact_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": run.get("status"),
        "current_phase": run.get("current_phase"),
        "mode": run.get("mode"),
        "summary": run.get("summary"),
        "final_decision": run.get("final_decision"),
    }


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": event.get("event_type"),
        "phase": event.get("phase"),
        "status": event.get("status"),
        "actor": event.get("actor"),
        "summary": event.get("summary") or event.get("title"),
        "reason": event.get("reason"),
        "created_at": str(event.get("created_at") or ""),
    }


def _json_default(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose why an Agent Run did or did not dispatch production tasks.")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(diagnose(args.run_id)), ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
