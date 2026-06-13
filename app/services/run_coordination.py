from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.services.agent_run_snapshot import _effective_tasks_for_state, get_agent_run_snapshot
from app.services.agent_runtime import publish_agent_event
from app.services.agent_run_state_machine import (
    ACTIVE_STATUSES,
    TERMINAL_FAILED,
    evaluate_action_gate,
    evaluate_production_stages,
    recommend_next_action,
)


PACKET_VERSION = "main_run_chain_phase1"


@dataclass(frozen=True)
class UnifiedRunFacts:
    run: dict[str, Any]
    shots: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    production_run: dict[str, Any]
    source: str = "unknown"
    planner_audit: dict[str, Any] = field(default_factory=dict)
    user_id: int | None = None


@dataclass(frozen=True)
class DecisionTickResult:
    packet_version: str
    status: str
    action: str
    stage_id: str
    selected_lane: str
    dispatchable: bool
    allowed: bool
    reason: str
    missing: list[str]
    fallback_action: str
    active_task_count: int
    failed_task_count: int
    allowed_writes: list[str]
    evidence: dict[str, Any]
    evidence_refs: list[dict[str, Any]]
    candidate_actions: list[dict[str, Any]]
    success_criteria: list[str]
    budget: dict[str, Any]
    risk: dict[str, Any]
    failure_policy: dict[str, Any]
    mission: dict[str, Any]
    root_cause_layer: str = ""
    decision_rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_decision_tick(facts: UnifiedRunFacts) -> DecisionTickResult:
    """Return the next read-only coordination decision for a run."""
    deferred_tasks = [task for task in facts.tasks if _is_deferred_provider_failure(task, facts.production_run)]
    active_tasks = [
        task
        for task in facts.tasks
        if str(task.get("status") or "") in ACTIVE_STATUSES or task in deferred_tasks
    ]
    failed_tasks = [
        task
        for task in facts.tasks
        if str(task.get("status") or "") in TERMINAL_FAILED and task not in deferred_tasks
    ]
    candidates = _candidate_actions(facts)

    if active_tasks:
        waiting_for_provider = bool(deferred_tasks) and not any(
            str(task.get("status") or "") in ACTIVE_STATUSES for task in active_tasks
        )
        return _decision_result(
            facts=facts,
            status="wait",
            action="wait_for_provider" if waiting_for_provider else "wait_for_tasks",
            stage_id="",
            allowed=False,
            reason=(
                "Provider capacity is deferred; wait for provider retry or availability."
                if waiting_for_provider
                else "Active production tasks are still running."
            ),
            missing=[],
            fallback_action="",
            active_task_count=len(active_tasks),
            failed_task_count=len(failed_tasks),
            success_criteria=["Wait until all active tasks reach a terminal status."],
            candidates=candidates,
        )

    recommendation = recommend_next_action(
        shots=facts.shots,
        tasks=facts.tasks,
        production_run=facts.production_run,
    )
    evidence = _build_evidence(facts)
    recommendation = _apply_final_edit_compatibility(recommendation, evidence=evidence)
    action = str(recommendation.get("action") or "")
    gate = evaluate_action_gate(
        action,
        shots=facts.shots,
        tasks=facts.tasks,
        production_run=facts.production_run,
    )
    stage_id = str(gate.get("stage_id") or recommendation.get("stage_id") or "")
    missing = [str(item) for item in gate.get("missing") or []]

    if failed_tasks and not _has_enough_output_to_continue(facts, action):
        recovery_action = str(gate.get("recovery") or recommendation.get("action") or "recover_failed_tasks")
        return _decision_result(
            facts=facts,
            status="recover",
            action=recovery_action,
            stage_id=stage_id,
            allowed=False,
            reason=str(gate.get("reason") or "A terminal task failure requires recovery before continuing."),
            missing=missing,
            fallback_action="fallback_reasoning",
            active_task_count=0,
            failed_task_count=len(failed_tasks),
            success_criteria=_success_criteria(recovery_action),
            candidates=candidates,
        )

    if _is_completed_policy_with_final_artifact(recommendation, evidence=evidence):
        return _decision_result(
            facts=facts,
            status="complete",
            action="writeback_review",
            stage_id="writeback_review",
            allowed=True,
            reason="Final video artifact is available and production policy is complete.",
            missing=[],
            fallback_action="",
            active_task_count=0,
            failed_task_count=len(failed_tasks),
            success_criteria=["Final video URL is present.", "Run can be summarized for the user."],
            candidates=candidates,
        )

    if not bool(gate.get("allowed", recommendation.get("allowed", False))):
        return _decision_result(
            facts=facts,
            status="blocked",
            action=action,
            stage_id=stage_id,
            allowed=False,
            reason=str(gate.get("reason") or recommendation.get("reason") or "Runtime gate blocked the action."),
            missing=missing,
            fallback_action=str(gate.get("recovery") or "fallback_reasoning"),
            active_task_count=0,
            failed_task_count=len(failed_tasks),
            success_criteria=_success_criteria(action),
            candidates=candidates,
        )

    return _decision_result(
        facts=facts,
        status="execute",
        action=action,
        stage_id=stage_id,
        allowed=True,
        reason=str(recommendation.get("reason") or gate.get("reason") or ""),
        missing=[],
        fallback_action=str(gate.get("recovery") or ""),
        active_task_count=0,
        failed_task_count=len(failed_tasks),
        success_criteria=_success_criteria(action),
        candidates=candidates,
    )


async def load_run_facts_from_snapshot(db: AsyncSession, *, run_id: str, user_id: int) -> UnifiedRunFacts | None:
    snapshot = await get_agent_run_snapshot(db, run_id=run_id, user_id=user_id)
    if not snapshot:
        return None
    outputs = snapshot.get("outputs") if isinstance(snapshot.get("outputs"), dict) else {}
    shots = list(outputs.get("shots") or snapshot.get("ledger", {}).get("shots") or snapshot.get("shots") or [])
    # Reuse snapshot's effective-task semantics so superseded failed media tasks do not force recovery.
    tasks = _effective_tasks_for_state(tasks=list(snapshot.get("tasks") or []), shots=shots)
    run = dict(snapshot.get("run") or {})
    run_meta = run.get("meta") if isinstance(run.get("meta"), dict) else {}
    planner_audit = run_meta.get("planner_audit") if isinstance(run_meta.get("planner_audit"), dict) else {}
    return UnifiedRunFacts(
        run=run,
        shots=shots,
        tasks=tasks,
        production_run=_production_run_from_snapshot(snapshot, outputs=outputs),
        source="agent_run_snapshot",
        planner_audit=planner_audit,
        user_id=user_id,
    )


async def observe_task_terminal_decision_tick(task_id: str) -> dict[str, Any] | None:
    """Log a read-only coordination decision after a task reaches terminal state."""
    if not _is_uuid(task_id):
        return None
    async with AsyncSessionLocal() as session:
        context = await _task_run_context(session, task_id)
        if not context:
            return None
        existing = await _existing_decision_event(session, task_id=task_id)
        if existing is not None:
            return existing
        facts = await load_run_facts_from_snapshot(
            session,
            run_id=str(context["run_id"]),
            user_id=int(context["user_id"]),
        )
        if not facts:
            return None
        decision = evaluate_decision_tick(facts)
        await _insert_decision_event(session, context=context, task_id=task_id, decision=decision)
        await session.commit()
        return decision.as_dict()


async def _task_run_context(session: AsyncSession, task_id: str) -> dict[str, Any] | None:
    if not _is_uuid(task_id):
        return None
    row = (
        await session.execute(
            text(
                """
                SELECT task_id, run_id, project_id, user_id
                FROM tasks
                WHERE task_id = CAST(:task_id AS UUID)
                  AND run_id IS NOT NULL
                LIMIT 1
                """
            ),
            {"task_id": task_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def task_run_context_for_main_chain(session: AsyncSession, task_id: str) -> dict[str, Any] | None:
    context = await _task_run_context(session, task_id)
    if not context:
        return None

    # 从 users 表取真实 user_tier，替代硬编码 "free"
    user_id = context.get("user_id")
    user_tier = "free"
    if user_id:
        row = (
            await session.execute(
                text(
                    """
                    SELECT CASE
                        WHEN tier != 'free' AND tier_expires_at IS NOT NULL AND tier_expires_at < NOW() THEN 'free'
                        ELSE tier
                    END AS tier
                    FROM users
                    WHERE id = :user_id
                    LIMIT 1
                    """
                ),
                {"user_id": user_id},
            )
        ).scalar_one_or_none()
        if row:
            user_tier = row

    return {
        **context,
        "user_tier": user_tier,
        "run_mode": "autopilot",
    }


async def _existing_decision_event(session: AsyncSession, *, task_id: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT meta
                FROM agent_events
                WHERE source = 'state_machine'
                  AND event_type = 'decision'
                  AND phase = 'decision_tick'
                  AND task_id = CAST(:task_id AS UUID)
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"task_id": task_id},
        )
    ).mappings().first()
    if not row:
        return None
    meta = _json_object(row.get("meta"))
    decision = meta.get("decision_tick")
    return dict(decision) if isinstance(decision, Mapping) else None


async def _insert_decision_event(
    session: AsyncSession,
    *,
    context: dict[str, Any],
    task_id: str,
    decision: DecisionTickResult,
) -> None:
    await publish_agent_event(
        session,
        run_id=str(context["run_id"]),
        project_id=str(context["project_id"]),
        task_id=task_id,
        user_id=int(context["user_id"]),
        source="state_machine",
        event_type="decision",
        phase="decision_tick",
        title="Run coordination decision tick",
        detail=f"{decision.status}: {decision.action}",
        status=decision.status,
        progress=None,
        meta={"decision_tick": decision.as_dict()},
        event_kind="decision",
        visibility="debug",
        summary=f"{decision.status}: {decision.action}",
        reason=decision.reason,
    )


def _decision_result(
    *,
    facts: UnifiedRunFacts,
    status: str,
    action: str,
    stage_id: str,
    allowed: bool,
    reason: str,
    missing: list[str],
    fallback_action: str,
    active_task_count: int,
    failed_task_count: int,
    candidates: list[dict[str, Any]],
    success_criteria: list[str],
) -> DecisionTickResult:
    lane = _selected_lane(action, status=status)
    fallback = fallback_action or ""
    dispatchable = status == "execute" and allowed and bool(action) and lane in {
        "a_lane_project_brain",
        "c_lane_production",
    }
    audit = facts.planner_audit
    root_cause = str(audit.get("root_cause_layer") or "")
    rationale = str(audit.get("decision_rationale") or "")
    evidence_refs = list(_evidence_refs(facts, action))
    audit_refs = audit.get("evidence_refs")
    if isinstance(audit_refs, list):
        for ref in audit_refs:
            if isinstance(ref, dict) and ref not in evidence_refs:
                evidence_refs.append(ref)
    return DecisionTickResult(
        packet_version=PACKET_VERSION,
        status=status,
        action=action,
        stage_id=stage_id,
        selected_lane=lane,
        dispatchable=dispatchable,
        allowed=allowed,
        reason=reason,
        missing=missing,
        fallback_action=fallback,
        active_task_count=active_task_count,
        failed_task_count=failed_task_count,
        allowed_writes=_allowed_writes(action),
        evidence=_build_evidence(facts),
        evidence_refs=evidence_refs,
        candidate_actions=candidates,
        success_criteria=success_criteria,
        budget=_budget_hint(facts, action, status=status),
        risk=_risk_hint(action, failed_task_count=failed_task_count, status=status),
        failure_policy=_failure_policy(status=status, fallback_action=fallback),
        mission=_mission_payload(facts, action, stage_id=stage_id, lane=lane) if dispatchable else {},
        root_cause_layer=root_cause,
        decision_rationale=rationale,
    )


def _candidate_actions(facts: UnifiedRunFacts) -> list[dict[str, Any]]:
    rows = evaluate_production_stages(
        shots=facts.shots,
        tasks=facts.tasks,
        production_run=facts.production_run,
    )
    candidates = [
        {
            "action": row["action"],
            "stage_id": row["id"],
            "status": row["status"],
            "allowed": bool(row.get("gate", {}).get("allowed")),
            "reason": str(row.get("gate", {}).get("reason") or ""),
        }
        for row in rows
        if row["status"] in {"pending", "blocked", "running"}
    ]
    return _apply_candidate_compatibility(candidates, facts=facts)[:3]


def _apply_final_edit_compatibility(recommendation: dict[str, Any], *, evidence: dict[str, Any]) -> dict[str, Any]:
    # Compatibility adapter: the production policy still lists audio/subtitles before final_cut,
    # while Task 2's read-only coordinator intentionally routes selected videos to final edit.
    if recommendation.get("action") != "audio_subtitles" or not evidence["selected_video_count"]:
        return recommendation
    return {
        **recommendation,
        "action": "plan_final_edit",
        "stage_id": "final_cut",
        "status": "pending",
        "reason": "",
        "allowed": True,
    }


def _apply_candidate_compatibility(
    candidates: list[dict[str, Any]],
    *,
    facts: UnifiedRunFacts,
) -> list[dict[str, Any]]:
    if not any(shot.get("selected_video") for shot in facts.shots):
        return candidates
    final_cut = next((candidate for candidate in candidates if candidate["action"] == "plan_final_edit"), None)
    if not final_cut:
        return candidates
    rest = [candidate for candidate in candidates if candidate["action"] not in {"audio_subtitles", "plan_final_edit"}]
    return [final_cut, *rest]


def _build_evidence(facts: UnifiedRunFacts) -> dict[str, Any]:
    return {
        "run_id": str(facts.run.get("run_id") or facts.run.get("id") or ""),
        "project_id": str(facts.run.get("project_id") or ""),
        "goal": str(facts.run.get("goal") or ""),
        "shot_count": len(facts.shots),
        "selected_image_count": sum(1 for shot in facts.shots if shot.get("selected_image")),
        "selected_video_count": sum(1 for shot in facts.shots if shot.get("selected_video")),
        "final_video_url": str(facts.production_run.get("final_video_url") or ""),
        "source": facts.source,
    }


def _selected_lane(action: str, *, status: str) -> str:
    if status == "wait" or action.startswith("wait_") or not action:
        return "main_chain"
    from app.services.action_registry import lane_for_action
    return lane_for_action(action)


def _allowed_writes(action: str) -> list[str]:
    from app.services.action_registry import allowed_writes_for_action
    return allowed_writes_for_action(action)


def _evidence_refs(facts: UnifiedRunFacts, action: str) -> list[dict[str, Any]]:
    refs = [{"kind": "shot_rows", "project_id": str(facts.run.get("project_id") or "")}]
    run_id = str(facts.run.get("run_id") or facts.run.get("id") or "")
    if run_id:
        refs.append({"kind": "agent_run", "run_id": run_id})
    if action == "plan_final_edit":
        refs.append(
            {
                "kind": "final_video_candidates",
                "selected_video_count": sum(1 for shot in facts.shots if shot.get("selected_video")),
            }
        )
    return refs


def _budget_hint(facts: UnifiedRunFacts, action: str, *, status: str) -> dict[str, Any]:
    if status != "execute":
        return {"unit": "", "target_count": 0, "estimated_max_credits": None, "source": "non_dispatchable"}
    if action == "generate_keyframes":
        return {
            "unit": "image_gen",
            "target_count": max(0, len(facts.shots) - sum(1 for shot in facts.shots if shot.get("selected_image"))),
            "estimated_max_credits": None,
            "source": "fact_hint",
        }
    if action == "generate_videos":
        return {
            "unit": "video_gen_5s",
            "target_count": max(
                0,
                sum(1 for shot in facts.shots if shot.get("selected_image"))
                - sum(1 for shot in facts.shots if shot.get("selected_video")),
            ),
            "estimated_max_credits": None,
            "source": "fact_hint",
        }
    return {"unit": "", "target_count": 0, "estimated_max_credits": None, "source": "fact_hint"}


def _risk_hint(action: str, *, failed_task_count: int, status: str) -> dict[str, Any]:
    level = "high" if action == "generate_videos" else "medium" if action in {"generate_keyframes", "plan_final_edit"} else "low"
    if status in {"recover", "blocked"} and failed_task_count > 0:
        level = "high"
    return {
        "level": level,
        "failed_task_count": failed_task_count,
        "requires_human": status in {"recover", "blocked"},
    }


def _failure_policy(*, status: str, fallback_action: str) -> dict[str, Any]:
    return {
        "fallback_action": fallback_action,
        "retryable": status in {"execute", "recover"},
        "require_human_confirmation": status in {"recover", "blocked"},
    }


def _mission_payload(
    facts: UnifiedRunFacts,
    action: str,
    *,
    stage_id: str,
    lane: str,
) -> dict[str, Any]:
    run_id = str(facts.run.get("run_id") or facts.run.get("id") or "")
    return {
        "mission_id": f"{run_id}:{stage_id or action}",
        "lane": lane,
        "action": action,
        "write_scope": _allowed_writes(action),
        "idempotency_key": f"{run_id}:{action}",
    }


def _is_completed_policy_with_final_artifact(
    recommendation: dict[str, Any],
    *,
    evidence: dict[str, Any],
) -> bool:
    return bool(evidence["final_video_url"] and recommendation.get("status") == "completed")


def _production_run_from_snapshot(snapshot: dict[str, Any], *, outputs: dict[str, Any]) -> dict[str, Any]:
    production_run = dict(snapshot.get("production_run") or {})
    production_run.update(dict(outputs.get("production_run") or {}))

    summary = outputs.get("summary") if isinstance(outputs.get("summary"), dict) else {}
    final_video_url = str(production_run.get("final_video_url") or summary.get("final_video_url") or "").strip()
    if final_video_url:
        production_run["final_video_url"] = final_video_url

    run = snapshot.get("run") if isinstance(snapshot.get("run"), dict) else {}
    state_machine = snapshot.get("state_machine") if isinstance(snapshot.get("state_machine"), dict) else {}
    current_phase = str(run.get("current_phase") or "").strip()
    run_status = str(run.get("status") or "").strip()

    if current_phase:
        production_run.setdefault("current_stage", current_phase)
    elif state_machine.get("stage"):
        production_run.setdefault("current_stage", str(state_machine.get("stage") or ""))

    if current_phase == "provider_waiting":
        production_run["status"] = "provider_waiting"
    elif not production_run.get("status") and run_status in {"completed", "failed", "cancelled", "provider_waiting", "running"}:
        production_run["status"] = run_status

    return production_run


def _has_enough_output_to_continue(facts: UnifiedRunFacts, action: str) -> bool:
    if action == "plan_final_edit":
        return sum(1 for s in facts.shots if s.get("selected_video")) >= len(facts.shots)
    if action == "generate_videos":
        return sum(1 for s in facts.shots if s.get("selected_image")) >= len(facts.shots)
    return False


def _is_deferred_provider_failure(task: dict[str, Any], production_run: dict[str, Any]) -> bool:
    if str(production_run.get("status") or "") != "provider_waiting":
        return False
    if str(task.get("task_type") or "") != "video_gen":
        return False
    if str(task.get("status") or "") not in TERMINAL_FAILED:
        return False
    message = str(task.get("error_message") or "").lower()
    return any(token in message for token in ("saturated", "backpressure", "too many requests", "429", "rate limit"))


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _success_criteria(action: str) -> list[str]:
    return {
        "generate_story_plan": ["Generate script/storyboard rows.", "Persist shot_rows for downstream media generation."],
        "generate_keyframes": ["Generate selected_image for target shot rows.", "Write image candidates and review evidence."],
        "generate_videos": ["Generate selected_video for ready shot rows.", "Write video variants and provider evidence."],
        "plan_final_edit": ["Create final edit plan from selected videos.", "Produce or prepare final video export."],
        "writeback_review": ["Summarize final artifacts and update run completion evidence."],
    }.get(action, ["Record the decision outcome and expose the next observable state."])
