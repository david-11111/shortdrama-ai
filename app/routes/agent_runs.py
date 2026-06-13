import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from jose import JWTError
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.config import get_settings
from app.db import get_db
from app.middleware.credits import reserve_credits
from app.middleware.auth import get_current_user
from app.routes.director import director_export_preview
from app.routes.workbench import continue_project_brain, start_video_production
from app.security.audit import log_admin_action
from app.security.token_blacklist import is_token_blacklisted
from app.services.credits import credit_service
from app.services.cost_guard import assert_cost_guard
from app.services.agent_runtime import create_agent_run, list_project_agent_events, normalize_run_mode, publish_agent_event, update_agent_run
from app.services.agent_runtime_contract import RuntimeDecision, decide_runtime_action
from app.services.agent_run_snapshot import get_agent_run_snapshot
from app.services.agent_run_state_machine import evaluate_action_gate, infer_continue_action_decision, recommend_next_action
from app.services.auth import decode_token, get_token_jti
from app.services.agent_action_executor import ActionContext, dispatch_agent_action
from app.services.agent_control_registry import HUMAN_EXECUTABLE_ACTIONS, allowed_recommendations_for_tool, domain_for_action, domain_for_recommendation, followup_action_for_recommendation, is_control_diagnostic_tool
from app.services.agent_control_tools import classify_control_intent, diagnose_keyframe_pool_from_snapshot, diagnose_outputs_from_snapshot, diagnose_provider_writeback_from_snapshot, diagnose_script_from_snapshot, diagnose_tasks_from_snapshot
from app.services.agent_evidence_composer import compose_evidence_reply
from app.services.agent_semantic_controller import (
    actionable_followup_message,
    attach_semantic_control,
    build_verification_plan,
    classify_controller_intent,
    classify_target_domain,
    classify_utterance,
)
from app.services.fallback_reasoning import (
    FallbackTrigger,
    attempt_fallback,
    is_eligible_for_fallback,
)
from app.services.llm_planner import plan_human_instruction
from app.services.llm_stream import publish_planner_thinking, stream_pregenerated_reply
from app.services.director_preflight import analyze_shot_risk
from app.services.provider_prompt_adapter import adapt_provider_payload


router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])

HUMAN_CONTINUE_ACTIONS = HUMAN_EXECUTABLE_ACTIONS

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


@router.post("")
async def create_run(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    payload = body or {}
    project_id = str(payload.get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")

    user_id = int(current_user["id"])
    await _ensure_project_owner(db, project_id=project_id, user_id=user_id)

    mode = normalize_run_mode(str(payload.get("mode") or "step"))
    action = str(payload.get("action") or "continue_project").strip().lower()
    goal = str(payload.get("goal") or "").strip()
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    input_assets = _normalize_input_assets(params.get("input_assets") or payload.get("input_assets"))
    if input_assets:
        params = {**params, "input_assets": input_assets}

    if action == "production_run":
        production_body = {
            **params,
            "goal": goal or params.get("goal") or "生成一条短剧预览",
            "mode": mode,
            "allowed_max_credits": payload.get("allowed_max_credits", params.get("allowed_max_credits", 0)),
        }
        if not await _project_has_storyboard_shots(db, project_id=project_id, user_id=user_id):
            result = await continue_project_brain(
                project_id=project_id,
                body={
                    **production_body,
                    "action": "generate_story_plan",
                    "instruction": production_body["goal"],
                    "mode": mode,
                    "routed_from": "production_run_missing_storyboard",
                    "_stop_after_planning": False,
                    "production_run_chain": True,
                },
                db=db,
                current_user=current_user,
            )
            result["routed_from"] = "production_run_missing_storyboard"
            await _publish_input_assets_event(
                db,
                run_id=str(result.get("run_id") or ""),
                project_id=project_id,
                user_id=user_id,
                input_assets=input_assets,
            )
            return {
                "run_id": result.get("run_id"),
                "project_id": project_id,
                "status": result.get("status", "running"),
                "mode": mode,
                "action": "continue_project",
                "result": result,
            }
        result = await start_video_production(
            project_id=project_id,
            body=production_body,
            db=db,
            current_user=current_user,
        )
        await _publish_input_assets_event(
            db,
            run_id=str(result.get("agent_run_id") or ""),
            project_id=project_id,
            user_id=user_id,
            input_assets=input_assets,
        )
        return {
            "run_id": result.get("agent_run_id"),
            "project_id": project_id,
            "status": result.get("status") or "queued",
            "mode": mode,
            "action": action,
            "task_id": result.get("task_id"),
            "production_run_id": result.get("production_run_id"),
        }

    if action != "continue_project":
        raise HTTPException(status_code=400, detail=f"unsupported agent run action: {action}")

    continue_body = _build_continue_body(payload=payload, params=params, mode=mode, goal=goal)
    if mode == "autopilot":
        continue_body["allowed_max_credits"] = int(continue_body.get("allowed_max_credits") or 0)

    result = await continue_project_brain(
        project_id=project_id,
        body=continue_body,
        db=db,
        current_user=current_user,
    )
    run_id = result.get("run_id")
    await _publish_input_assets_event(
        db,
        run_id=str(run_id or ""),
        project_id=project_id,
        user_id=user_id,
        input_assets=input_assets,
    )
    return {
        "run_id": run_id,
        "project_id": project_id,
        "status": result.get("status", "completed" if mode in {"preview", "autopilot"} else "running"),
        "mode": mode,
        "action": action,
        "result": result,
    }


@router.get("/{run_id}/snapshot")
async def get_run_snapshot(
    run_id: str,
    event_limit: int = Query(300, ge=1, le=1000),
    task_limit: int = Query(300, ge=1, le=1000),
    artifact_limit: int = Query(120, ge=1, le=500),
    evidence_item_limit: int = Query(80, ge=1, le=300),
    stream_limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    snapshot = await get_agent_run_snapshot(
        db,
        run_id=run_id,
        user_id=int(current_user["id"]),
        event_limit=event_limit,
        task_limit=task_limit,
        artifact_limit=artifact_limit,
        evidence_item_limit=evidence_item_limit,
        stream_limit=stream_limit,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    return snapshot


@router.get("/{run_id}/events")
async def get_run_events(
    run_id: str,
    limit: int = Query(100, ge=1, le=300),
    event_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    project_id = await _ensure_run_owner(db, run_id=run_id, user_id=user_id)
    events = await list_project_agent_events(
        db,
        project_id=project_id,
        user_id=user_id,
        limit=limit,
        run_id=run_id,
        event_type=event_type,
    )
    return {
        "run_id": run_id,
        "project_id": project_id,
        "events": events,
        "items": events,
        "total": len(events),
    }


@router.get("/{run_id}/stream")
async def stream_run_events(
    run_id: str,
    token: str = Query(""),
    history_limit: int = Query(300, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _user_id_from_stream_token(token)
    project_id = await _ensure_run_owner(db, run_id=run_id, user_id=user_id)
    history = await list_project_agent_events(
        db,
        project_id=project_id,
        user_id=user_id,
        run_id=run_id,
        limit=history_limit,
    )
    current_status = await _get_run_status(db, run_id=run_id, user_id=user_id)

    async def event_stream():
        seen = set()
        for event in _stream_history_order(history):
            seen.add(str(event["id"]))
            yield _sse("execution_event", event, event_id=str(event["id"]))

        yield _sse("stream_ready", {"run_id": run_id, "project_id": project_id, "status": current_status})
        if current_status == "cancelled":
            yield _sse("stream_done", {"run_id": run_id, "project_id": project_id, "status": current_status})
            return

        redis = aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(f"project:{project_id}:events")
            idle_ticks = 0
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    try:
                        event = json.loads(message["data"])
                    except json.JSONDecodeError:
                        continue
                    if str(event.get("run_id") or "") != run_id:
                        continue
                    evt_type = str(event.get("type") or "execution_event")
                    if evt_type in ("llm_stream_start", "llm_chunk", "llm_stream_end"):
                        yield _sse(evt_type, event, event_id=event.get("stream_id"))
                        continue
                    event_id = str(event.get("id") or "")
                    if event_id and event_id in seen:
                        continue
                    if event_id:
                        seen.add(event_id)
                    yield _sse("execution_event", event, event_id=event_id or None)
                    if str(event.get("status") or "") in {"completed", "done", "failed", "blocked", "cancelled"} and str(event.get("phase") or "") in {"completed", "failed", "blocked", "cancelled", "writeback_review"}:
                        status = await _get_run_status(db, run_id=run_id, user_id=user_id)
                        if status == "cancelled":
                            yield _sse("stream_done", {"run_id": run_id, "project_id": project_id, "status": status})
                            return
                else:
                    idle_ticks += 1
                    if idle_ticks % 15 == 0:
                        status = await _get_run_status(db, run_id=run_id, user_id=user_id)
                        yield _sse("heartbeat", {"run_id": run_id, "status": status})
                        if status == "cancelled":
                            yield _sse("stream_done", {"run_id": run_id, "project_id": project_id, "status": status})
                            return
                await asyncio.sleep(0)
        finally:
            await pubsub.unsubscribe(f"project:{project_id}:events")
            await pubsub.close()
            await redis.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{run_id}/actions/retry-failed")
async def retry_failed_run_videos(
    run_id: str,
    body: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    project_id = await _ensure_run_owner(db, run_id=run_id, user_id=user_id)
    async with _run_action_lock(db, run_id=run_id, action="retry_failed"):
        await _ensure_run_can_dispatch(db, run_id=run_id, user_id=user_id, action="retry_failed")
        await _reset_retryable_video_shots(db, run_id=run_id, project_id=project_id, user_id=user_id)
        result = await continue_project_brain(
            project_id=project_id,
            body={**(body or {}), "action": "generate_videos", "_chain_run_id": run_id},
            db=db,
            current_user=current_user,
        )
        await _audit_agent_run_action(
            user_id=user_id,
            action="agent_run.retry_failed",
            run_id=run_id,
            project_id=project_id,
            payload={"dispatched_run_id": result.get("run_id"), "status": result.get("status")},
        )
        return {"run_id": run_id, "project_id": project_id, "action": "retry_failed", "result": result}


@router.post("/{run_id}/actions/change-provider")
async def change_provider_and_retry(
    run_id: str,
    body: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    provider = str((body or {}).get("provider") or "kling").strip().lower()
    if provider not in {"seedance", "kling", "ltx2.3", "wan2.1", "wan2_1", "wan", "ltx", "comfyui"}:
        raise HTTPException(status_code=400, detail="provider must be a valid video provider (seedance, kling, ltx2.3, etc.)")
    user_id = int(current_user["id"])
    project_id = await _ensure_run_owner(db, run_id=run_id, user_id=user_id)
    async with _run_action_lock(db, run_id=run_id, action="change_provider"):
        await _ensure_run_can_dispatch(db, run_id=run_id, user_id=user_id, action="change_provider")
        await _reset_retryable_video_shots(db, run_id=run_id, project_id=project_id, user_id=user_id)
        result = await continue_project_brain(
            project_id=project_id,
            body={**(body or {}), "action": "generate_videos", "video_provider": provider, "_chain_run_id": run_id},
            db=db,
            current_user=current_user,
        )
        await _audit_agent_run_action(
            user_id=user_id,
            action="agent_run.change_provider",
            run_id=run_id,
            project_id=project_id,
            payload={"provider": provider, "dispatched_run_id": result.get("run_id"), "status": result.get("status")},
        )
        return {"run_id": run_id, "project_id": project_id, "action": "change_provider", "provider": provider, "result": result}


@router.post("/{run_id}/actions/continue-step")
async def continue_run_step(
    run_id: str,
    body: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    project_id = await _ensure_run_owner(db, run_id=run_id, user_id=user_id)
    continue_body, routing = _build_human_continue_body(body or {}, source_run_id=run_id)
    pending_action = await _load_pending_action(db, run_id=run_id, user_id=user_id)
    if pending_action and _should_confirm_pending_action(routing):
        continue_body, routing = _apply_pending_action_confirmation(continue_body, routing, pending_action)
    recent_human_events = await _recent_human_dialogue_context(db, run_id=run_id, project_id=project_id, user_id=user_id)
    continue_body, routing = await _apply_planner_routing(
        body or {},
        continue_body,
        routing,
        source_run_id=run_id,
        user_id=user_id,
        project_context_extra={"recent_human_events": recent_human_events},
    )
    continue_body, routing = _apply_control_intent_routing(continue_body, routing)
    planner_for_semantic = routing.get("planner") if isinstance(routing.get("planner"), dict) else {}
    continue_body, routing = attach_semantic_control(continue_body, routing, planner=planner_for_semantic)
    async with _run_action_lock(db, run_id=run_id, action="continue_step"):
        current_status = await _get_run_status_for_update(db, run_id=run_id, user_id=user_id)
        if current_status == "cancelled":
            raise HTTPException(
                status_code=409,
                detail={"message": "Cannot continue_step; agent run is cancelled", "action": "continue_step", "run_id": run_id, "status": current_status},
            )
        continue_body, routing = await _apply_state_machine_recovery_routing(
            db,
            continue_body,
            routing,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
        )
        continue_body, routing = await _apply_review_blocker_clarification_routing(
            db,
            continue_body,
            routing,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
        )
        continue_body, routing = await _apply_video_review_blocker_clarification_routing(
            db,
            continue_body,
            routing,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
        )
        # A completed run can still be used as conversation context. Follow-up
        # production work is dispatched into a new child run by continue_project_brain.
        planner = routing.get("planner") if isinstance(routing.get("planner"), dict) else {}
        if planner:
            dispatch_ready = bool(planner.get("dispatch_ready"))
            planner_reply = str(planner.get("reply") or "").strip()
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source=str(planner.get("source") or "planner"),
                event_type="decision",
                phase="llm_planner",
                title="DeepSeek 中控判断",
                detail=planner_reply or str(planner.get("reason") or "DeepSeek 已判断下一步。"),
                status="done",
                progress=72,
                meta={"planner": planner, "routing": routing},
                actor="deepseek",
                event_kind="decision",
                visibility="debug",
                summary=planner_reply or f"DeepSeek 判断下一步是 {planner.get('action') or routing.get('resolved_action') or 'conversation'}",
                reason=str(planner.get("reason") or "DeepSeek 根据人工输入判断是否需要继续对话或派发。"),
                debug={"planner": planner, "routing": routing},
            )
            # Persist planner audit fields to run meta for downstream decision ticks
            audit_rationale = str(planner.get("decision_rationale") or "").strip()
            audit_root_cause = str(planner.get("root_cause_layer") or "").strip()
            audit_evidence = planner.get("evidence_refs") if isinstance(planner.get("evidence_refs"), list) else []
            if audit_rationale or audit_root_cause or audit_evidence:
                await update_agent_run(
                    db,
                    run_id=run_id,
                    meta_updates={
                        "planner_audit": {
                            "decision_rationale": audit_rationale,
                            "root_cause_layer": audit_root_cause,
                            "evidence_refs": audit_evidence,
                        }
                    },
                )
            # Publish planner thinking to frontend
            if planner and str(planner.get("source") or "") == "deepseek":
                import asyncio as _asyncio
                _asyncio.ensure_future(
                    publish_planner_thinking(
                        project_id=project_id,
                        run_id=run_id,
                        decision=planner,
                    )
                )
        active = await _active_run_task_summary(db, run_id=run_id, user_id=user_id)
        runtime_decision = decide_runtime_action(routing=routing, active_tasks=active, current_status=current_status)
        routing["runtime_decision"] = runtime_decision.as_dict(include_debug=False)
        if runtime_decision.kind == "inspect" and runtime_decision.reason == "inspect_only_ceiling":
            routing["resolved_action"] = "status_query"
            continue_body["action"] = "status_query"
            continue_body.pop("continue_action", None)
            continue_body["human_routing"] = routing

        # ==== FALLBACK REASONING HOOK (Trigger 1/5) ====
        # When the policy chain returns reject/ask, attempt creative reasoning
        # via the fallback module before giving up.
        if runtime_decision.kind in {"reject", "ask"}:
            fallback_count = routing.get("_fallback_count", 0)
            remaining_budget = routing.get("budget", {}).get("remaining_run_budget", 0)
            has_production_state = bool(
                routing.get("resolved_action")
                or routing.get("planner", {}).get("action")
            )
            eligible, _skip_reason = is_eligible_for_fallback(
                runtime_decision.kind,
                runtime_decision.reason,
                has_production_state=has_production_state,
                remaining_budget=remaining_budget,
                fallback_count=fallback_count,
            )
            if eligible:
                trigger = FallbackTrigger(
                    source="runtime_decision",
                    kind=runtime_decision.kind,
                    parent_decision=runtime_decision.as_dict(include_debug=False),
                    reason=runtime_decision.reason,
                )
                fallback_result = await attempt_fallback(
                    db,
                    run_id=run_id,
                    project_id=project_id,
                    user_id=user_id,
                    instruction=str(routing.get("instruction", "")),
                    trigger=trigger,
                    fallback_count=fallback_count,
                )
                routing["_fallback_count"] = fallback_count + 1
                if fallback_result.recommendation:
                    rec = fallback_result.recommendation
                    routing["fallback_recommendation"] = {
                        "action": rec.action,
                        "params": rec.params,
                        "user_message": rec.user_message,
                        "confidence": rec.confidence,
                        "requires_human_confirmation": rec.requires_human_confirmation,
                        "dispatch_ready": rec.dispatch_ready,
                        "fallback_kind": rec.fallback_kind,
                        "used_recovery_pattern": fallback_result.used_recovery_pattern,
                    }
                    if rec.fallback_kind == "resolved" and rec.dispatch_ready:
                        # Override routing with fallback recommendation and re-evaluate
                        routing["resolved_action"] = rec.action
                        routing["routing_source"] = "fallback_reasoning"
                        runtime_decision = decide_runtime_action(
                            routing=routing, active_tasks=active, current_status=current_status,
                        )
                        routing["runtime_decision"] = runtime_decision.as_dict(include_debug=False)
                        # If fallback-unlocked, proceed to the execute branch below
                    elif rec.fallback_kind == "partial":
                        # Return ask-style answer from fallback
                        answer = rec.user_message or "我需要先确认更多信息。"
                        # (falls through to the 'ask' branch below, which will use this answer)
                        runtime_decision = RuntimeDecision(
                            kind="ask",
                            action="",
                            user_message=answer,
                            reason=f"fallback_partial:{rec.reasoning[:200]}",
                        )
                        routing["runtime_decision"] = runtime_decision.as_dict(include_debug=False)
                    else:
                        # escalate — fall through to the 'reject' branch below
                        answer = rec.user_message or "当前情况需要人工处理。"
                        runtime_decision = RuntimeDecision(
                            kind="reject",
                            action="",
                            user_message=answer,
                            reason=f"fallback_escalate:{rec.reasoning[:200]}",
                        )
                        routing["runtime_decision"] = runtime_decision.as_dict(include_debug=False)

        if runtime_decision.kind == "reject":
            answer = runtime_decision.user_message or "当前指令不能执行。"
            event_meta = {
                **routing,
                "active_task_count": active["count"],
                "active_task_ids": active["task_ids"],
                "active_task_statuses": active["statuses"],
                "active_tasks": active.get("items", []),
                "answer": answer,
                "executor": "RuntimeController",
            }
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source="api",
                event_type="decision",
                phase="runtime_policy",
                title="中控拒绝执行",
                detail=answer,
                status="failed",
                progress=75,
                meta=event_meta,
                actor="executor",
                event_kind="recovery",
                visibility="user",
                summary=answer,
                reason="中控能力表或状态机策略不允许执行该指令。",
                debug={"routing": routing, "active_tasks": active, "runtime_decision": runtime_decision.as_dict(include_debug=True)},
            )
            await db.commit()
            await _audit_agent_run_action(
                user_id=user_id,
                action="agent_run.runtime_rejected",
                run_id=run_id,
                project_id=project_id,
                payload=event_meta,
            )
            return {
                "run_id": run_id,
                "project_id": project_id,
                "action": "continue_step",
                "status": "rejected",
                "executor": "RuntimeController",
                "answer": answer,
                "routing": routing,
                "active_tasks": active,
                "result": None,
            }
        if runtime_decision.kind == "ask":
            answer = runtime_decision.user_message or "我需要先确认更多信息，再决定是否派发生产任务。"
            event_meta = {
                **routing,
                "active_task_count": active["count"],
                "active_task_ids": active["task_ids"],
                "active_task_statuses": active["statuses"],
                "active_tasks": active.get("items", []),
                "answer": answer,
                "executor": "DeepSeekConversation",
            }
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source=str(planner.get("source") or "deepseek"),
                event_type="tool_result",
                phase="human_response",
                title="DeepSeek 先答复人工输入",
                detail=answer,
                status="done",
                progress=75,
                meta=event_meta,
                actor="deepseek",
                event_kind="tool_result",
                visibility="user",
                summary=answer,
                reason=str(planner.get("reason") or "当前输入还需要对话确认，暂不派发生产任务。"),
                debug={"routing": routing, "active_tasks": active},
            )
            await db.commit()
            await stream_pregenerated_reply(
                project_id=project_id, run_id=run_id, text=answer, actor="deepseek", phase="human_response",
            )
            await _audit_agent_run_action(
                user_id=user_id,
                action="agent_run.deepseek_conversation_answered",
                run_id=run_id,
                project_id=project_id,
                payload=event_meta,
            )
            return {
                "run_id": run_id,
                "project_id": project_id,
                "action": "continue_step",
                "status": "answered",
                "executor": "DeepSeekConversation",
                "answer": answer,
                "routing": routing,
                "active_tasks": active,
                "result": None,
            }
        is_deferred = runtime_decision.kind == "defer"
        if runtime_decision.kind == "execute" and str(routing.get("resolved_action") or "") not in {"", "status_query"}:
            await _approve_review_pending_keyframes_for_routing(
                db,
                project_id=project_id,
                user_id=user_id,
                routing=routing,
            )
            await _approve_review_pending_videos_for_routing(
                db,
                project_id=project_id,
                user_id=user_id,
                routing=routing,
            )
            await _ensure_action_gate_allows(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                action=str(routing.get("resolved_action") or ""),
            )
        event_meta = {
            **routing,
            "active_task_count": active["count"],
            "active_task_ids": active["task_ids"],
            "active_task_statuses": active["statuses"],
            "active_tasks": active.get("items", []),
        }
        human_event_status = "done" if routing.get("resolved_action") == "status_query" else "deferred" if is_deferred else "done"
        instruction_summary = _human_instruction_summary(routing)
        conversation_like = str(routing.get("intent_type") or "") in {"ui_diagnostic", "status_query", "conversation"}
        await publish_agent_event(
            db,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            source="api",
            event_type="decision",
            phase="human_instruction",
            title="DeepSeek 接收输入" if conversation_like else "接收人工输入",
            detail=str(routing.get("instruction") or ""),
            status=human_event_status,
            progress=75,
            meta=event_meta,
            actor="deepseek" if conversation_like else "executor",
            event_kind="decision",
            visibility="user",
            summary=instruction_summary,
            reason="DeepSeek 已接收当前输入，并决定先答复、检查或派发。" if conversation_like else "系统已接收当前输入，并根据 DeepSeek 判断决定答复或派发。",
            debug={"routing": routing, "active_tasks": active},
        )
        await db.commit()
        action_context = ActionContext(
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            action=str(routing.get("resolved_action") or ""),
            instruction=str(routing.get("instruction") or ""),
            routing=routing,
            continue_body=continue_body,
            current_status=current_status,
            active_tasks=active,
            diagnostics=await _build_control_diagnostics(db, run_id=run_id, user_id=user_id, routing=routing)
            if _needs_control_diagnostics(routing)
            else None,
        )

        async def execute_continue_project(payload: dict[str, Any]) -> dict[str, Any]:
            return await continue_project_brain(
                project_id=project_id,
                body=payload,
                db=db,
                current_user=current_user,
            )

        execution = await dispatch_agent_action(
            action_context,
            execute_continue_project=execute_continue_project,
        )
        if execution and execution.status == "answered":
            composer = await _compose_answer_from_evidence(
                instruction=action_context.instruction,
                fallback_answer=execution.answer,
                diagnostics=action_context.diagnostics,
                routing=routing,
                recent_human_events=recent_human_events,
                user_id=current_user["id"],
            )
            answer = composer.get("reply") if composer else execution.answer
            response_title = _answered_event_title(execution.executor)
            response_actor = "deepseek" if execution.executor in {"OutputDiagnosticExecutor", "StatusQueryExecutor", "TaskDiagnosticExecutor", "ProviderWritebackDiagnosticExecutor", "ScriptDiagnosticExecutor", "KeyframePoolDiagnosticExecutor"} else "executor"
            response_summary = answer or "已完成答复。"
            tool_result_meta = action_context.diagnostics or {}
            followup_action = _followup_action_from_evidence(composer=composer, diagnostics=tool_result_meta, routing=routing)
            if not followup_action and str(routing.get("resolved_action") or "") == "status_query":
                # Fallback: check production state for next pending stage
                fallback = await _production_stage_fallback_action(db, run_id=run_id, user_id=user_id)
                if fallback:
                    followup_action = fallback
            if followup_action:
                verification_plan = build_verification_plan(followup_action, diagnostics=tool_result_meta)
                if not composer or not bool(composer.get("dispatch_ready")):
                    action_message = actionable_followup_message(action=followup_action, active_count=int(active.get("count") or 0))
                    answer = _merge_actionable_answer(answer, action_message)
                response_summary = answer
                event_meta["verification_plan"] = verification_plan
            else:
                pending_action = _pending_action_from_evidence(
                    composer=composer,
                    diagnostics=tool_result_meta,
                    routing=routing,
                    instruction=action_context.instruction,
                )
                if pending_action:
                    await _save_pending_action(
                        db,
                        run_id=run_id,
                        user_id=user_id,
                        pending_action=pending_action,
                        current_goal=action_context.instruction,
                        routing=routing,
                        answer=answer,
                    )
                    event_meta["pending_action"] = pending_action
                    answer = _merge_pending_action_answer(answer, pending_action)
                    response_summary = answer
            if followup_action and int(active.get("count") or 0) > 0:
                answer = _merge_actionable_answer(
                    answer,
                    f"我已经把后续处理动作暂存为 {followup_action}，等当前活动任务结束后再执行，避免重复派发或覆盖产物。",
                )
                response_summary = answer
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source="api",
                event_type="tool_result",
                phase="human_response",
                title=response_title,
                detail=answer,
                status="done",
                progress=75,
                meta={
                    **event_meta,
                    "answer": answer,
                    "executor": execution.executor,
                    "tool_result": tool_result_meta,
                    "evidence_composer": composer or {},
                },
                actor=response_actor,
                event_kind="tool_result",
                visibility="user",
                summary=response_summary,
                reason=_answered_event_reason(execution.executor),
                debug={"routing": routing, "active_tasks": active},
            )
            await db.commit()
            await stream_pregenerated_reply(
                project_id=project_id, run_id=run_id, text=answer or "", actor=response_actor, phase="human_response",
            )
            await _audit_agent_run_action(
                user_id=user_id,
                action=execution.audit_action,
                run_id=run_id,
                project_id=project_id,
                payload={**event_meta, "answer": answer, "executor": execution.executor, "evidence_composer": composer or {}},
            )
            response = execution.response(action_context)
            response["answer"] = answer
            if composer:
                response["evidence_composer"] = composer
            result_pending_action = (execution.result or {}).get("pending_action") if isinstance(execution.result, dict) else None
            if isinstance(result_pending_action, dict) and result_pending_action.get("action"):
                await _save_pending_action(
                    db,
                    run_id=run_id,
                    user_id=user_id,
                    pending_action=result_pending_action,
                    current_goal=action_context.instruction,
                    routing=routing,
                    answer=answer,
                )
                await db.commit()
                response["pending_action"] = result_pending_action
            if followup_action:
                followup_payload = _followup_continue_body(continue_body, routing=routing, action=followup_action)
                if int(active.get("count") or 0) > 0:
                    followup_label = _action_display_name(followup_action)
                    pending_instruction = {
                        "status": "queued",
                        "instruction": action_context.instruction,
                        "continue_body": followup_payload,
                        "routing": {**routing, "resolved_action": followup_action, "followup_from_tool": True},
                    }
                    await publish_agent_event(
                        db,
                        run_id=run_id,
                        project_id=project_id,
                        user_id=user_id,
                        source="api",
                        event_type="tool_result",
                        phase="human_response",
                        title="后续处理已暂存",
                        detail=answer,
                        status="deferred",
                        progress=75,
                        meta={**event_meta, "pending_instruction": pending_instruction, "followup_action": followup_action},
                        actor="executor",
                        event_kind="recovery",
                        visibility="user",
                        summary=f"当前任务忙，{followup_label}已暂存",
                        reason="诊断已给出可执行动作，但当前仍有活动任务，先暂存避免重复派发。",
                        debug={"routing": routing, "active_tasks": active, "pending_instruction": pending_instruction},
                    )
                    await db.commit()
                    response["status"] = "deferred"
                    response["followup_action"] = followup_action
                    response["pending_instruction"] = pending_instruction
                    return response
                await _ensure_action_gate_allows(
                    db,
                    run_id=run_id,
                    project_id=project_id,
                    user_id=user_id,
                    action=followup_action,
                )
                result = await execute_continue_project(followup_payload)
                followup_label = _action_display_name(followup_action)
                await publish_agent_event(
                    db,
                    run_id=run_id,
                    project_id=project_id,
                    user_id=user_id,
                    source="api",
                    event_type="tool_call",
                    phase="executor_dispatch",
                    title="Executor 已执行诊断建议",
                    detail=f"已派发{followup_label}，当前状态：{_status_display_name(str(result.get('status') or ''))}",
                    status="dispatched",
                    progress=80,
                    meta={**event_meta, "followup_action": followup_action, "result": result},
                    actor="executor",
                    event_kind="dispatch",
                    visibility="user",
                    summary=f"已按诊断结果派发{followup_label}",
                    reason="工具诊断给出可执行修复动作，且当前没有活动任务阻塞。",
                    debug={"routing": routing, "result": result},
                )
                await db.commit()
                await _audit_agent_run_action(
                    user_id=user_id,
                    action="agent_run.diagnostic_followup_dispatched",
                    run_id=run_id,
                    project_id=project_id,
                    payload={"followup_action": followup_action, "result": result, **routing},
                )
                await _clear_pending_action(db, run_id=run_id, user_id=user_id)
                response["status"] = "dispatched"
                response["followup_action"] = followup_action
                response["result"] = result
            return response
        if execution and execution.status == "deferred":
            pending_instruction = {
                "status": "queued",
                "instruction": action_context.instruction,
                "continue_body": continue_body,
                "routing": routing,
            }
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source="api",
                event_type="tool_result",
                phase="human_response",
                title="人工指令已暂存",
                detail=execution.answer,
                status="deferred",
                progress=75,
                meta={**event_meta, "answer": execution.answer, "executor": execution.executor, "pending_instruction": pending_instruction},
                actor="executor",
                event_kind="recovery",
                visibility="user",
                summary="当前任务忙，人工指令已暂存",
                reason="避免重复派发、覆盖产物或造成资产不一致。",
                debug={"routing": routing, "active_tasks": active, "pending_instruction": pending_instruction},
            )
            await db.commit()
            await _audit_agent_run_action(
                user_id=user_id,
                action=execution.audit_action,
                run_id=run_id,
                project_id=project_id,
                payload={**event_meta, "answer": execution.answer, "executor": execution.executor, "pending_instruction": pending_instruction},
            )
            return execution.response(action_context)
        if execution and execution.status == "requested_action":
            requested = dict(execution.result or {})
            requested_action = str(requested.get("requested_action") or action_context.action)
            requested_body = dict(requested.get("continue_body") or continue_body)
            requested_body["action"] = requested_action
            await _ensure_action_gate_allows(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                action=requested_action,
            )
            if requested_action == "plan_final_edit" and str(routing.get("routing_source") or "") != "pending_action_confirm":
                await _ensure_no_active_export(db, run_id=run_id, project_id=project_id, user_id=user_id)
                selected_video_rows = await _selected_video_rows(db, project_id=project_id, user_id=user_id)
                shot_indices = [int(row["shot_index"]) for row in selected_video_rows]
                expired_rows = [
                    row for row in selected_video_rows
                    if _signed_media_url_expired(str(row.get("selected_video") or ""))
                ]
                if expired_rows:
                    expired_indices = [int(row["shot_index"]) for row in expired_rows]
                    pending_action = {
                        "action": "generate_videos",
                        "continue_action": "generate_videos",
                        "recommendation": "regenerate_expired_videos",
                        "shot_indices": expired_indices,
                        "reason": "selected_video_url_expired",
                    }
                    answer = "视频链接已经过期，不能直接剪辑成片。需要先重新生成或刷新这些镜头的视频，再进入最终剪辑。"
                    await _save_pending_action(
                        db,
                        run_id=run_id,
                        user_id=user_id,
                        pending_action=pending_action,
                        current_goal=action_context.instruction,
                        routing=routing,
                        answer=answer,
                    )
                    await publish_agent_event(
                        db,
                        run_id=run_id,
                        project_id=project_id,
                        user_id=user_id,
                        source="api",
                        event_type="tool_result",
                        phase="executor_dispatch",
                        title="FinalEditExecutor 已阻断过期视频",
                        detail=answer,
                        status="blocked",
                        progress=80,
                        meta={**event_meta, "executor": "FinalEditExecutor", "pending_action": pending_action, "expired_shot_indices": expired_indices},
                        actor="executor",
                        event_kind="recovery",
                        visibility="user",
                        summary="视频链接已经过期",
                        reason="最终剪辑前必须保证 selected_video URL 可用。",
                        debug={"routing": routing, "selected_video_rows": selected_video_rows},
                    )
                    await db.commit()
                    return {
                        "run_id": run_id,
                        "project_id": project_id,
                        "action": "continue_step",
                        "status": "answered",
                        "executor": "FinalEditExecutor",
                        "routing": routing,
                        "active_tasks": active,
                        "answer": answer,
                        "pending_action": pending_action,
                        "result": {
                            "status": "blocked",
                            "reason": "selected_video_url_expired",
                            "expired_shot_indices": expired_indices,
                        },
                    }

                result = await director_export_preview(
                    body={
                        **(body or {}),
                        "action": "plan_final_edit",
                        "project_id": project_id,
                        "shot_indices": shot_indices,
                        "ignore_saved_plan": True,
                        "run_id": run_id,
                    },
                    db=db,
                    current_user=current_user,
                )
                result = {**result, "shot_indices": shot_indices}
                if routing.get("pending_action"):
                    await _clear_pending_action(db, run_id=run_id, user_id=user_id)
                action_label = _action_display_name(requested_action)
                await publish_agent_event(
                    db,
                    run_id=run_id,
                    project_id=project_id,
                    user_id=user_id,
                    source="api",
                    event_type="tool_call",
                    phase="executor_dispatch",
                    title="FinalEditExecutor 已派发任务",
                    detail=f"已派发{action_label}任务，当前状态：{_status_display_name(str(result.get('status') or ''))}",
                    status="dispatched",
                    progress=80,
                    meta={**event_meta, "executor": "FinalEditExecutor", "result": result},
                    actor="executor",
                    event_kind="dispatch",
                    visibility="user",
                    summary=f"已派发{action_label}",
                    reason="状态机允许且当前没有活动任务，进入最终剪辑导出环节。",
                    debug={"routing": routing, "result": result},
                )
                await db.commit()
                await _audit_agent_run_action(
                    user_id=user_id,
                    action="agent_run.final_edit_dispatched",
                    run_id=run_id,
                    project_id=project_id,
                    payload={"dispatched_run_id": result.get("run_id"), "status": result.get("status"), "executor": "FinalEditExecutor", **routing},
                )
                return {
                    "run_id": run_id,
                    "project_id": project_id,
                    "action": "continue_step",
                    "status": "dispatched",
                    "executor": "FinalEditExecutor",
                    "routing": routing,
                    "active_tasks": active,
                    "result": result,
                }

            result = await execute_continue_project(requested_body)
            action_label = _action_display_name(requested_action)
            if routing.get("pending_action"):
                await _clear_pending_action(db, run_id=run_id, user_id=user_id)
            executor_name = "VisualAssetExecutor" if requested_action == "plan_visual_assets" else execution.executor
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source="api",
                event_type="tool_call",
                phase="executor_dispatch",
                title="Executor 已提交动作意图",
                detail=f"已将{action_label}交给主链处理，当前状态：{_status_display_name(str(result.get('status') or ''))}",
                status="dispatched",
                progress=80,
                meta={**event_meta, "executor": executor_name, "requested_action": requested_action, "result": result},
                actor="executor",
                event_kind="dispatch",
                visibility="user",
                summary=f"已通过主链派发{action_label}",
                reason="B lane 只提交动作意图，写操作由项目主链和 dispatch gateway 执行。",
                debug={"routing": routing, "result": result},
            )
            await db.commit()
            await _audit_agent_run_action(
                user_id=user_id,
                action=execution.audit_action,
                run_id=run_id,
                project_id=project_id,
                payload={"requested_action": requested_action, "dispatched_run_id": result.get("run_id"), "status": result.get("status"), **routing},
            )
            response = execution.response(action_context)
            response["executor"] = executor_name
            response["status"] = "dispatched"
            response["result"] = result
            return response
        if execution and execution.status == "dispatched":
            result = execution.result or {}
            action_label = _action_display_name(str(routing.get("resolved_action") or "brain_next"))
            if routing.get("pending_action"):
                await _clear_pending_action(db, run_id=run_id, user_id=user_id)
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source="api",
                event_type="tool_call",
                phase="executor_dispatch",
                title="Executor 已派发任务",
                detail=f"已派发{action_label}任务，当前状态：{_status_display_name(str(result.get('status') or ''))}",
                status="dispatched",
                progress=80,
                meta={**event_meta, "executor": execution.executor, "result": result},
                actor="executor",
                event_kind="dispatch",
                visibility="user",
                summary=f"已派发{action_label}",
                reason="状态机允许且当前没有活动任务，进入对应生产环节。",
                debug={"routing": routing, "result": result},
            )
            await db.commit()
            await _audit_agent_run_action(
                user_id=user_id,
                action=execution.audit_action,
                run_id=run_id,
                project_id=project_id,
                payload={"dispatched_run_id": result.get("run_id"), "status": result.get("status"), "executor": execution.executor, **routing},
            )
            return execution.response(action_context)
        result = await execute_continue_project(continue_body)
        action_label = _action_display_name(str(routing.get("resolved_action") or "brain_next"))
        if routing.get("pending_action"):
            await _clear_pending_action(db, run_id=run_id, user_id=user_id)
        await publish_agent_event(
            db,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            source="api",
            event_type="tool_call",
            phase="executor_dispatch",
            title="Executor 已交给项目大脑继续",
            detail=f"已交给项目大脑继续处理{action_label}，当前状态：{_status_display_name(str(result.get('status') or ''))}",
            status="dispatched",
            progress=80,
            meta={**event_meta, "executor": "ProjectBrainExecutor", "result": result},
            actor="executor",
            event_kind="dispatch",
            visibility="user",
            summary=f"已派发{action_label}",
            reason="该动作由项目大脑继续处理，执行前已完成状态与活动任务检查。",
            debug={"routing": routing, "result": result},
        )
        await db.commit()
        await _audit_agent_run_action(
            user_id=user_id,
            action="agent_run.continue_step",
            run_id=run_id,
            project_id=project_id,
            payload={"dispatched_run_id": result.get("run_id"), "status": result.get("status"), **routing},
        )
        return {"run_id": run_id, "project_id": project_id, "action": "continue_step", "routing": routing, "result": result}


@router.post("/{run_id}/actions/export-partial")
async def export_partial_run(
    run_id: str,
    body: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    project_id = await _ensure_run_owner(db, run_id=run_id, user_id=user_id)
    async with _run_action_lock(db, run_id=run_id, action="export_partial"):
        status = await _get_run_status_for_update(db, run_id=run_id, user_id=user_id)
        if status == "cancelled":
            raise HTTPException(
                status_code=409,
                detail={"message": "Cannot export; agent run is cancelled", "run_id": run_id, "status": status},
            )
        await _ensure_no_active_export(db, run_id=run_id, project_id=project_id, user_id=user_id)
        shot_indices = await _selected_video_shot_indices(db, project_id=project_id, user_id=user_id)
        if not shot_indices:
            raise HTTPException(status_code=400, detail="No selected videos available for partial export")
        result = await director_export_preview(
            body={
                **(body or {}),
                "project_id": project_id,
                "shot_indices": shot_indices,
                "ignore_saved_plan": True,
                "run_id": run_id,
            },
            db=db,
            current_user=current_user,
        )
        await _audit_agent_run_action(
            user_id=user_id,
            action="agent_run.export_partial",
            run_id=run_id,
            project_id=project_id,
            payload={"shot_indices": shot_indices, "task_id": result.get("task_id"), "status": result.get("status")},
        )
        return {"run_id": run_id, "project_id": project_id, "action": "export_partial", "shot_indices": shot_indices, "result": result}


@router.post("/{run_id}/actions/keyframe-batch/preview")
async def preview_keyframe_batch(
    run_id: str,
    body: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    project_id = await _ensure_run_owner(db, run_id=run_id, user_id=user_id)
    payload = body or {}
    shot_index = _positive_int(payload.get("shot_index"), field="shot_index")
    count = _bounded_count(payload.get("count"), default=3, max_count=4)
    shot = await _load_shot_for_keyframe_pool(db, project_id=project_id, user_id=user_id, shot_index=shot_index)
    prompts = _build_keyframe_variation_prompts(
        shot,
        count=count,
        strategy=str(payload.get("variation_strategy") or "mixed"),
        instruction=str(payload.get("instruction") or payload.get("goal") or ""),
    )
    unit_price = await credit_service.get_price("image_gen")
    return {
        "run_id": run_id,
        "project_id": project_id,
        "action": "preview_keyframe_batch",
        "shot_index": shot_index,
        "count": count,
        "unit_price": unit_price,
        "estimated_credits": count * int(unit_price or 0),
        "prompts": prompts,
        "dry_run": True,
    }


@router.post("/{run_id}/actions/generate-keyframe-batch")
async def generate_keyframe_batch(
    run_id: str,
    body: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    project_id = await _ensure_run_owner(db, run_id=run_id, user_id=user_id)
    payload = body or {}
    shot_index = _positive_int(payload.get("shot_index"), field="shot_index")
    count = _bounded_count(payload.get("count"), default=3, max_count=4)
    async with _run_action_lock(db, run_id=run_id, action=f"generate_keyframe_batch:{shot_index}"):
        await _ensure_run_can_dispatch(db, run_id=run_id, user_id=user_id, action="generate_keyframe_batch")
        current_status = await _get_run_status_for_update(db, run_id=run_id, user_id=user_id)
        if current_status in {"completed", "cancelled"}:
            raise HTTPException(status_code=409, detail={"message": "Cannot generate keyframe batch for terminal run", "run_id": run_id, "status": current_status})
        shot = await _load_shot_for_keyframe_pool(db, project_id=project_id, user_id=user_id, shot_index=shot_index)
        prompts = _build_keyframe_variation_prompts(
            shot,
            count=count,
            strategy=str(payload.get("variation_strategy") or "mixed"),
            instruction=str(payload.get("instruction") or payload.get("goal") or ""),
        )
        unit_price = int(await credit_service.get_price("image_gen") or 0)
        total_cost = count * unit_price
        await assert_cost_guard(db, user_id=user_id, credits_to_reserve=total_cost)
        transaction_ids: list[str] = []
        task_ids: list[str] = []
        task_payloads: list[dict[str, Any]] = []
        try:
            for _ in range(count):
                transaction_ids.append(await reserve_credits(user_id, "image_gen", 1))
            priority = {"free": 5, "pro": 3, "enterprise": 1}.get(str(current_user.get("tier") or "free").lower(), 5)
            for index, prompt_item in enumerate(prompts):
                task_id = str(__import__("uuid").uuid4())
                task_ids.append(task_id)
                task_payload = {
                    "provider": str(payload.get("provider") or "seedream"),
                    "project_id": project_id,
                    "run_id": run_id,
                    "shot_index": shot_index,
                    "prompt": prompt_item["prompt"],
                    "variation": prompt_item["variation"],
                    "keyframe_pool_batch": True,
                    "shot_row": {**shot, "prompt": prompt_item["prompt"], "project_id": project_id, "user_id": user_id},
                }
                for semantic_key in ("intent_brief", "semantic_plan", "constraint_packet", "verification_plan", "human_routing"):
                    if isinstance(payload.get(semantic_key), dict):
                        task_payload[semantic_key] = payload[semantic_key]
                task_payload = adapt_provider_payload(task_payload, task_type="image_gen", provider=str(task_payload.get("provider") or "seedream"))
                task_payloads.append(task_payload)
                await db.execute(
                    text(
                        """
                        INSERT INTO tasks (task_id, user_id, project_id, run_id, task_type, status, priority, payload, credits_reserved, credit_transaction_id)
                        VALUES (:task_id, :user_id, :project_id, CAST(:run_id AS UUID), 'image_gen', 'queued', :priority, CAST(:payload AS JSONB), :credits, :credit_transaction_id)
                        """
                    ),
                    {
                        "task_id": task_id,
                        "user_id": user_id,
                        "project_id": project_id,
                        "run_id": run_id,
                        "priority": priority,
                        "payload": json.dumps({**task_payload, "_credit_transaction_id": transaction_ids[index]}, ensure_ascii=False, default=str),
                        "credits": unit_price,
                        "credit_transaction_id": transaction_ids[index],
                    },
                )
            await db.execute(
                text("UPDATE shot_rows SET status = 'generating_image', updated_at = NOW() WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :shot_index"),
                {"project_id": project_id, "user_id": user_id, "shot_index": shot_index},
            )
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source="queue",
                event_type="tool_call",
                phase="generate_keyframe_batch",
                title="批量关键帧任务已派发",
                detail=f"shot_index={shot_index}; count={count}; credits={total_cost}",
                status="queued",
                progress=55,
                meta={"shot_index": shot_index, "count": count, "child_task_ids": task_ids, "estimated_credits": total_cost, "prompts": prompts},
                actor="executor",
                event_kind="dispatch",
                visibility="user",
                summary=f"第 {shot_index} 镜已派发 {count} 张候选关键帧",
                reason="图片池批量生成走现有 image_gen worker，并受成本、并发和 run 锁控制。",
            )
            await update_agent_run(db, run_id=run_id, status="dispatching", current_phase="generate_keyframe_batch", summary=f"Queued {count} keyframe candidate task(s).", final_decision=f"queued {count} keyframe candidates", reserved_credits_delta=total_cost)
            await db.commit()
        except Exception:
            await db.rollback()
            for transaction_id in transaction_ids:
                try:
                    await credit_service.refund(transaction_id)
                except Exception:
                    pass
            raise
        for index, task_id in enumerate(task_ids):
            celery_app.send_task("app.tasks.image_tasks.generate_image_task", args=[task_id, str(user_id), task_payloads[index]], kwargs={"transaction_id": transaction_ids[index]}, queue="image", priority=priority)
        await _audit_agent_run_action(user_id=user_id, action="agent_run.generate_keyframe_batch", run_id=run_id, project_id=project_id, payload={"shot_index": shot_index, "count": count, "task_ids": task_ids, "credits": total_cost})
        return {"run_id": run_id, "project_id": project_id, "action": "generate_keyframe_batch", "shot_index": shot_index, "count": count, "task_ids": task_ids, "estimated_credits": total_cost, "status": "queued"}


@router.post("/{run_id}/actions/select-keyframe-candidate")
async def select_keyframe_candidate(
    run_id: str,
    body: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    project_id = await _ensure_run_owner(db, run_id=run_id, user_id=user_id)
    payload = body or {}
    shot_index = _positive_int(payload.get("shot_index"), field="shot_index")
    candidate_url = str(payload.get("url") or payload.get("candidate_url") or "").strip()
    artifact_id = str(payload.get("artifact_id") or "").strip()
    async with _run_action_lock(db, run_id=run_id, action=f"select_keyframe_candidate:{shot_index}"):
        shot = await _load_shot_for_keyframe_pool(db, project_id=project_id, user_id=user_id, shot_index=shot_index)
        selected = await _resolve_keyframe_candidate_url(db, project_id=project_id, user_id=user_id, shot=shot, artifact_id=artifact_id, candidate_url=candidate_url)
        image_candidates = _mark_selected_keyframe_candidate_review_approved(
            shot.get("image_candidates") if isinstance(shot.get("image_candidates"), list) else [],
            selected,
        )
        await db.execute(
            text(
                """
                UPDATE shot_rows
                SET selected_image = :selected_image,
                    image_candidates_json = CAST(:image_candidates AS JSONB),
                    status = CASE WHEN selected_video IS NULL OR selected_video = '' THEN 'image_done' ELSE status END,
                    updated_at = NOW()
                WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :shot_index
                """
            ),
            {
                "selected_image": selected,
                "image_candidates": json.dumps(image_candidates, ensure_ascii=False),
                "project_id": project_id,
                "user_id": user_id,
                "shot_index": shot_index,
            },
        )
        await publish_agent_event(
            db,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            source="api",
            event_type="tool_result",
            phase="select_keyframe_candidate",
            title="已选择关键帧候选图",
            detail=f"shot_index={shot_index}",
            status="done",
            progress=70,
            meta={"shot_index": shot_index, "selected_image": selected, "artifact_id": artifact_id},
            actor="executor",
            event_kind="tool_result",
            visibility="user",
            summary=f"第 {shot_index} 镜主图已更新",
            reason="用户或中控选择了图片池候选图，写入 selected_image 作为后续视频输入。",
        )
        await db.commit()
        await _audit_agent_run_action(user_id=user_id, action="agent_run.select_keyframe_candidate", run_id=run_id, project_id=project_id, payload={"shot_index": shot_index, "artifact_id": artifact_id, "selected_image": selected})
        return {"run_id": run_id, "project_id": project_id, "action": "select_keyframe_candidate", "shot_index": shot_index, "selected_image": selected, "status": "done"}


def _mark_selected_keyframe_candidate_review_approved(candidates: list[Any], selected_url: str, *, approved_by: str = "human_selection") -> list[Any]:
    selected = str(selected_url or "").strip()
    if not selected:
        return candidates
    updated: list[Any] = []
    matched = False
    for item in candidates:
        if not isinstance(item, dict):
            updated.append(item)
            continue
        url = str(item.get("url") or item.get("uri") or item.get("image_url") or "").strip()
        if url != selected:
            updated.append(item)
            continue
        review = item.get("review") if isinstance(item.get("review"), dict) else {}
        approved_review = {
            **review,
            "status": "approved",
            "approved_by": approved_by,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        updated.append({**item, "review": approved_review, "review_status": "approved"})
        matched = True
    if not matched:
        updated.append(
            {
                "url": selected,
                "review": {
                    "status": "approved",
                    "approved_by": approved_by,
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                },
                "review_status": "approved",
            }
        )
    return updated


@router.post("/{run_id}/actions/generate-video-from-pool")
async def generate_video_from_pool(
    run_id: str,
    body: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    project_id = await _ensure_run_owner(db, run_id=run_id, user_id=user_id)
    payload = body or {}
    shot_index = _positive_int(payload.get("shot_index"), field="shot_index")
    mode = str(payload.get("mode") or "best_single").strip().lower()
    if mode != "best_single":
        raise HTTPException(
            status_code=400,
            detail={
                "message": "generate_video_from_pool currently supports best_single only",
                "mode": mode,
                "supported_modes": ["best_single"],
                "reason": "Multi-image morph sequence is not enabled until provider support is verified.",
            },
        )
    provider = _normalize_video_pool_provider(payload.get("provider") or "ltx2.3")
    duration = _bounded_video_duration(payload.get("duration"), default=15)
    operation = _video_operation_for_duration(duration)

    async with _run_action_lock(db, run_id=run_id, action=f"generate_video_from_pool:{shot_index}"):
        await _ensure_run_can_dispatch(db, run_id=run_id, user_id=user_id, action="generate_video_from_pool")
        shot = await _load_shot_for_keyframe_pool(db, project_id=project_id, user_id=user_id, shot_index=shot_index)
        candidate_url = str(payload.get("url") or payload.get("candidate_url") or "").strip()
        artifact_id = str(payload.get("artifact_id") or "").strip()
        selected_image = await _resolve_keyframe_candidate_url(
            db,
            project_id=project_id,
            user_id=user_id,
            shot=shot,
            artifact_id=artifact_id,
            candidate_url=candidate_url or str(shot.get("selected_image") or "").strip(),
        )
        shot = {**shot, "selected_image": selected_image, "image_url": selected_image, "project_id": project_id, "user_id": user_id, "duration": duration}
        await db.execute(
            text(
                """
                UPDATE shot_rows
                SET selected_image = :selected_image,
                    status = 'image_done',
                    updated_at = NOW()
                WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :shot_index
                """
            ),
            {"selected_image": selected_image, "project_id": project_id, "user_id": user_id, "shot_index": shot_index},
        )
        await _ensure_action_gate_allows(db, run_id=run_id, project_id=project_id, user_id=user_id, action="generate_videos")

        unit_price = int(await credit_service.get_price(operation) or 0)
        await assert_cost_guard(db, user_id=user_id, credits_to_reserve=unit_price)
        transaction_id = ""
        task_id = str(__import__("uuid").uuid4())
        task_payload = {
            "provider": provider,
            "project_id": project_id,
            "run_id": run_id,
            "shot_index": shot_index,
            "prompt": str(shot.get("prompt") or ""),
            "duration": duration,
            "image_url": selected_image,
            "mode": mode,
            "keyframe_pool_video": True,
            "shot_row": shot,
        }
        if provider in {"ltx2.3", "wan", "wan2.1", "wan2_1"}:
            task_payload.update({"width": 1088, "height": 960, "steps": 10, "timeout_seconds": 3600})
        for semantic_key in ("intent_brief", "semantic_plan", "constraint_packet", "verification_plan", "human_routing"):
            if isinstance(payload.get(semantic_key), dict):
                task_payload[semantic_key] = payload[semantic_key]
        task_payload = adapt_provider_payload(task_payload, task_type="video_gen", provider=provider)
        priority = {"free": 5, "pro": 3, "enterprise": 1}.get(str(current_user.get("tier") or "free").lower(), 5)
        try:
            transaction_id = await reserve_credits(user_id, operation, 1)
            await db.execute(
                text(
                    """
                    INSERT INTO tasks (task_id, user_id, project_id, run_id, task_type, status, priority, payload, credits_reserved, credit_transaction_id)
                    VALUES (:task_id, :user_id, :project_id, CAST(:run_id AS UUID), 'video_gen', 'queued', :priority, CAST(:payload AS JSONB), :credits, :credit_transaction_id)
                    """
                ),
                {
                    "task_id": task_id,
                    "user_id": user_id,
                    "project_id": project_id,
                    "run_id": run_id,
                    "priority": priority,
                    "payload": json.dumps({**task_payload, "_credit_transaction_id": transaction_id}, ensure_ascii=False, default=str),
                    "credits": unit_price,
                    "credit_transaction_id": transaction_id,
                },
            )
            await db.execute(
                text("UPDATE shot_rows SET status = 'generating_video', updated_at = NOW() WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :shot_index"),
                {"project_id": project_id, "user_id": user_id, "shot_index": shot_index},
            )
            await publish_agent_event(
                db,
                run_id=run_id,
                project_id=project_id,
                user_id=user_id,
                source="queue",
                event_type="tool_call",
                phase="generate_video_from_pool",
                title="图片池视频任务已派发",
                detail=f"shot_index={shot_index}; provider={provider}; duration={duration}; credits={unit_price}",
                status="queued",
                progress=72,
                meta={"shot_index": shot_index, "child_task_ids": [task_id], "provider": provider, "duration": duration, "estimated_credits": unit_price, "mode": mode},
                actor="executor",
                event_kind="dispatch",
                visibility="user",
                summary=f"第 {shot_index} 镜已用图片池主图派发视频生成",
                reason="图片池视频生成复用现有 video_gen worker，并受状态机、成本、并发和 run 锁控制。",
            )
            await update_agent_run(db, run_id=run_id, status="dispatching", current_phase="generate_video_from_pool", summary=f"Queued video task for shot {shot_index}.", final_decision=f"queued video from keyframe pool for shot {shot_index}", reserved_credits_delta=unit_price)
            await db.commit()
        except Exception:
            await db.rollback()
            if transaction_id:
                try:
                    await credit_service.refund(transaction_id)
                except Exception:
                    pass
            raise
        celery_app.send_task("app.tasks.video_tasks.generate_video_task", args=[task_id, str(user_id), task_payload], kwargs={"transaction_id": transaction_id}, queue="video", priority=priority)
        await _audit_agent_run_action(user_id=user_id, action="agent_run.generate_video_from_pool", run_id=run_id, project_id=project_id, payload={"shot_index": shot_index, "task_id": task_id, "provider": provider, "duration": duration, "credits": unit_price})
        return {"run_id": run_id, "project_id": project_id, "action": "generate_video_from_pool", "shot_index": shot_index, "task_id": task_id, "provider": provider, "duration": duration, "estimated_credits": unit_price, "status": "queued"}


def _normalize_video_pool_provider(raw_provider: Any) -> str:
    provider = str(raw_provider or "ltx2.3").strip().lower()
    allowed = ["seedance", "kling", "ltx2.3", "wan", "wan2.1", "wan2_1", "ltx", "comfyui"]
    if provider not in set(allowed):
        raise HTTPException(
            status_code=400,
            detail={"message": "unsupported video provider", "provider": provider, "allowed": allowed},
        )
    return provider


@router.post("/{run_id}/actions/cancel")
async def cancel_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["id"])
    project_id = await _ensure_run_owner(db, run_id=run_id, user_id=user_id)
    async with _run_action_lock(db, run_id=run_id, action="cancel"):
        current_status = await _get_run_status_for_update(db, run_id=run_id, user_id=user_id)
        if current_status == "cancelled":
            return {
                "run_id": run_id,
                "project_id": project_id,
                "action": "cancel_run",
                "status": "cancelled",
                "idempotent": True,
                "cancelled_count": 0,
                "cancelled_task_ids": [],
                "refunded_credits": 0,
            }
        if current_status == "completed":
            raise HTTPException(
                status_code=409,
                detail={"message": "Cannot cancel; agent run is already completed", "action": "cancel", "run_id": run_id, "status": current_status},
            )
        cancelled = await _cancel_queued_run_tasks(db, run_id=run_id, user_id=user_id)
        await update_agent_run(
            db,
            run_id=run_id,
            status="cancelled",
            current_phase="cancelled",
            summary=f"Run cancelled by user. Cancelled queued tasks: {cancelled['cancelled_count']}.",
            final_decision="cancelled",
        )
        await publish_agent_event(
            db,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            source="api",
            event_type="risk",
            phase="cancelled",
            title="Run cancelled",
            detail=f"Cancelled queued/pending tasks={cancelled['cancelled_count']}; refunded_credits={cancelled['refunded_credits']}.",
            status="cancelled",
            progress=100,
            meta=cancelled,
        )
        await db.commit()
        await _audit_agent_run_action(
            user_id=user_id,
            action="agent_run.cancel",
            run_id=run_id,
            project_id=project_id,
            payload=cancelled,
        )
        return {"run_id": run_id, "project_id": project_id, "action": "cancel_run", "status": "cancelled", **cancelled}


async def _ensure_project_owner(db: AsyncSession, *, project_id: str, user_id: int) -> None:
    result = await db.execute(
        text("SELECT 1 FROM projects WHERE project_id = :project_id AND user_id = :user_id LIMIT 1"),
        {"project_id": project_id, "user_id": user_id},
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="project not found")


def _normalize_input_assets(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        asset_id = str(item.get("asset_id") or item.get("id") or "").strip()
        file_url = str(item.get("file_url") or item.get("url") or item.get("uri") or "").strip()
        if not asset_id or not file_url:
            continue
        asset_type = str(item.get("asset_type") or item.get("type") or "generic").strip().lower()
        if asset_type not in {"image", "video", "audio", "generic"}:
            asset_type = "generic"
        role = str(item.get("role") or "").strip()
        if not role:
            role = "golden_reference" if asset_type == "image" else "source_video" if asset_type == "video" else "input_asset"
        normalized.append(
            {
                "asset_id": asset_id,
                "asset_type": asset_type,
                "file_url": file_url,
                "role": role,
            }
        )
    return normalized[:20]


async def _publish_input_assets_event(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    input_assets: list[dict[str, Any]],
) -> None:
    if not run_id or not input_assets:
        return
    await publish_agent_event(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        source="api",
        event_type="artifact",
        phase="input_assets",
        title="入口资产已接收",
        detail=f"input_assets={len(input_assets)}",
        status="done",
        progress=2,
        meta={"input_assets": input_assets, "entrypoint": "/director/agent-run"},
        actor="user",
        event_kind="artifact",
        visibility="user",
        summary=f"已从唯一入口接收 {len(input_assets)} 个图片/视频资产",
        reason="用户在 /director/agent-run 上传或绑定的图片/视频作为本次运行的目标监督证据。",
    )
    await db.commit()


def _build_continue_body(*, payload: dict[str, Any], params: dict[str, Any], mode: str, goal: str) -> dict[str, Any]:
    instruction = str(payload.get("instruction") or params.get("instruction") or goal)
    continue_body = {
        **params,
        "mode": mode,
        "goal": goal,
        "instruction": instruction,
        "allowed_max_credits": payload.get("allowed_max_credits", params.get("allowed_max_credits", 0)),
    }
    explicit_action = str(payload.get("continue_action") or params.get("continue_action") or "").strip()
    intent = infer_continue_action_decision(goal) if not explicit_action else None
    if not explicit_action and not intent.action:
        intent = infer_continue_action_decision(instruction)
    continue_action = explicit_action or (intent.action if intent else "")
    if continue_action:
        continue_body["action"] = continue_action
    if intent and intent.action:
        continue_body["intent"] = intent.as_dict()
    return continue_body


def _build_human_continue_body(body: dict[str, Any], *, source_run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    instruction = str(body.get("instruction") or body.get("goal") or "").strip()
    action_hint = str(body.get("action_hint") or body.get("continue_action") or body.get("action") or "").strip()
    raw_action = str(body.get("continue_action") or body.get("action") or "").strip()
    force_manual_action = bool(body.get("force_manual_action")) or ("action_hint" not in body and bool(raw_action))
    explicit_action = raw_action if force_manual_action else ""
    if explicit_action and explicit_action not in HUMAN_CONTINUE_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Unsupported human instruction action",
                "action": explicit_action,
                "allowed_actions": sorted(HUMAN_CONTINUE_ACTIONS),
            },
        )

    intent = infer_continue_action_decision(instruction) if not explicit_action else None
    rule_action = "status_query" if _is_human_status_query(instruction) else ""
    resolved_action = explicit_action or rule_action or intent.action
    utterance = classify_utterance(instruction, explicit_action=bool(explicit_action))
    target_domain = classify_target_domain(instruction, action=resolved_action)
    routing = {
        "source_run_id": source_run_id,
        "instruction": instruction,
        "explicit_action": explicit_action,
        "action_hint": action_hint,
        "resolved_action": resolved_action,
        "intent": intent.as_dict() if intent and intent.action else {},
        "utterance": utterance.as_dict(),
        "utterance_type": utterance.utterance_type,
        "action_ceiling": utterance.action_ceiling,
        "target_domain": target_domain,
        "routing_source": "manual_selector" if explicit_action else ("status_query_rule" if rule_action else "natural_language_rule" if resolved_action else "brain_next_action"),
    }
    continue_body = {
        **body,
        "_chain_run_id": source_run_id,
        "source_run_id": source_run_id,
        "instruction": instruction,
        "goal": str(body.get("goal") or instruction),
        "mode": str(body.get("mode") or "step"),
        "human_intervention": True,
        "human_routing": routing,
    }
    if resolved_action:
        continue_body["action"] = resolved_action
        continue_body["continue_action"] = resolved_action
    if intent and intent.action:
        continue_body["intent"] = intent.as_dict()
    return continue_body, routing


async def _apply_planner_routing(
    body: dict[str, Any],
    continue_body: dict[str, Any],
    routing: dict[str, Any],
    *,
    source_run_id: str,
    user_id: int | None = None,
    project_context_extra: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if routing.get("routing_source") == "pending_action_confirm":
        return continue_body, routing
    if routing.get("explicit_action"):
        return continue_body, routing
    instruction = str(routing.get("instruction") or "")
    planner_context: dict[str, Any] = {"source_run_id": source_run_id, "rule_routing": routing}
    if user_id is not None:
        planner_context["user_id"] = user_id
    if project_context_extra:
        planner_context.update(project_context_extra)
    if routing.get("action_hint"):
        planner_context["action_hint"] = routing.get("action_hint") or ""
    decision = await plan_human_instruction(
        instruction,
        project_context=planner_context,
    )
    if not decision:
        return continue_body, routing
    planner_payload = decision.as_dict()
    resolved_action = decision.action if decision.dispatch_ready else ""
    routing_source = decision.source
    intent_type = str(planner_payload.get("intent_type") or "")
    if intent_type in {"ui_diagnostic", "status_query"} and not decision.dispatch_ready:
        resolved_action = ""
    elif intent_type == "ui_diagnostic":
        resolved_action = "status_query"
    target_domain = classify_target_domain(instruction, action=resolved_action)
    next_routing = {
        **routing,
        "resolved_action": resolved_action,
        "routing_source": routing_source,
        "intent_type": intent_type,
        "target_domain": target_domain,
        "planner": planner_payload,
    }
    next_body = {
        **continue_body,
        "human_routing": next_routing,
    }
    next_body.pop("continue_action", None)
    next_body.pop("action", None)
    if resolved_action:
        next_body["action"] = resolved_action
        next_body["continue_action"] = resolved_action
    if resolved_action == "status_query":
        next_body.pop("continue_action", None)
    return next_body, next_routing


def _apply_control_intent_routing(
    continue_body: dict[str, Any],
    routing: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if routing.get("routing_source") == "pending_action_confirm":
        return continue_body, routing
    if routing.get("explicit_action"):
        return continue_body, routing
    if _should_preserve_planner_final_edit(routing):
        return continue_body, routing
    controller = classify_controller_intent(str(routing.get("instruction") or ""))
    if controller:
        next_routing = {
            **routing,
            "resolved_action": controller.action,
            "routing_source": "control_tool",
            "intent_type": controller.intent_type,
            "target_domain": classify_target_domain(str(routing.get("instruction") or ""), action=controller.action),
            "control_tool": {
                "tool_name": controller.tool_name,
                "action": controller.action,
                "dispatch_ready": True,
                "reason": controller.reason,
            },
            "controller_intent": controller.as_dict(),
        }
        next_body = {
            **continue_body,
            "human_routing": next_routing,
            "action": controller.action,
        }
        if controller.action == "status_query":
            next_body.pop("continue_action", None)
        else:
            next_body["continue_action"] = controller.action
        return next_body, next_routing

    control = classify_control_intent(str(routing.get("instruction") or ""))
    if not control:
        return continue_body, routing
    next_routing = {
        **routing,
        "resolved_action": control.action,
        "routing_source": "control_tool",
        "intent_type": control.intent_type,
        "target_domain": classify_target_domain(str(routing.get("instruction") or ""), action=control.action),
        "control_tool": {
            "tool_name": control.tool_name,
            "action": control.action,
            "dispatch_ready": control.dispatch_ready,
            "reason": control.reason,
        },
    }
    next_body = {
        **continue_body,
        "human_routing": next_routing,
        "action": control.action,
    }
    if control.action == "status_query":
        next_body.pop("continue_action", None)
    else:
        next_body["continue_action"] = control.action
    return next_body, next_routing


async def _apply_state_machine_recovery_routing(
    db: AsyncSession,
    continue_body: dict[str, Any],
    routing: dict[str, Any],
    *,
    run_id: str,
    project_id: str,
    user_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if routing.get("routing_source") == "pending_action_confirm":
        return continue_body, routing
    if routing.get("explicit_action"):
        return continue_body, routing
    planner = routing.get("planner") if isinstance(routing.get("planner"), dict) else {}
    if not planner or bool(planner.get("dispatch_ready")):
        return continue_body, routing
    if str(routing.get("intent_type") or planner.get("intent_type") or "") != "production_action":
        return continue_body, routing
    action_ceiling = str(routing.get("action_ceiling") or (routing.get("utterance") or {}).get("action_ceiling") or "")
    utterance_type = str(routing.get("utterance_type") or (routing.get("utterance") or {}).get("utterance_type") or "")
    if action_ceiling != "execute_allowed" and utterance_type not in {"command", "confirm"}:
        return continue_body, routing

    state = await _run_production_state(db, run_id=run_id, project_id=project_id, user_id=user_id)
    next_action = recommend_next_action(
        shots=state["shots"],
        tasks=state["tasks"],
        production_run=state["production_run"],
    )
    gate = evaluate_action_gate(
        str(next_action.get("action") or ""),
        shots=state["shots"],
        tasks=state["tasks"],
        production_run=state["production_run"],
    )
    recovery_action = str(gate.get("recovery") or "").strip()
    planner_action = str(planner.get("action") or "").strip()
    if not recovery_action:
        return continue_body, routing
    if planner_action and planner_action != recovery_action:
        return continue_body, routing

    next_routing = {
        **routing,
        "resolved_action": recovery_action,
        "routing_source": "state_machine_recovery",
        "intent_type": "production_action",
        "target_domain": classify_target_domain(str(routing.get("instruction") or ""), action=recovery_action),
        "state_machine_recovery": {
            "action": recovery_action,
            "stage_id": gate.get("stage_id") or next_action.get("stage_id") or "",
            "reason": gate.get("reason") or next_action.get("reason") or "",
            "missing": gate.get("missing") or [],
            "planner_action": planner_action,
        },
    }


async def _project_has_storyboard_shots(db: AsyncSession, *, project_id: str, user_id: int) -> bool:
    result = await db.execute(
        text(
            """
            SELECT 1
            FROM shot_rows
            WHERE project_id = :project_id
              AND user_id = :user_id
              AND NULLIF(prompt, '') IS NOT NULL
            LIMIT 1
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    return result.fetchone() is not None
    next_body = {
        **continue_body,
        "action": recovery_action,
        "continue_action": recovery_action,
        "human_routing": next_routing,
    }
    return next_body, next_routing


async def _apply_review_blocker_clarification_routing(
    db: AsyncSession,
    continue_body: dict[str, Any],
    routing: dict[str, Any],
    *,
    run_id: str,
    project_id: str,
    user_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if routing.get("routing_source") == "pending_action_confirm" or routing.get("explicit_action"):
        return continue_body, routing
    action = str(routing.get("resolved_action") or continue_body.get("action") or "").strip()
    if action != "generate_keyframes" and not _is_keyframe_review_repair_intent(routing, continue_body):
        return continue_body, routing

    state = await _run_production_state(db, run_id=run_id, project_id=project_id, user_id=user_id)
    next_action = recommend_next_action(
        shots=state["shots"],
        tasks=state["tasks"],
        production_run=state["production_run"],
    )
    gate = evaluate_action_gate(
        str(next_action.get("action") or ""),
        shots=state["shots"],
        tasks=state["tasks"],
        production_run=state["production_run"],
    )
    missing = [str(item) for item in gate.get("missing") or []]
    if "image_review_blockers" not in set(missing):
        return continue_body, routing
    instruction = str(routing.get("instruction") or "")
    if _has_keyframe_revision_details(instruction):
        return continue_body, routing

    proposal = _build_keyframe_review_repair_proposal(state["shots"])
    if proposal:
        labels = _format_shot_indices(proposal["shot_indices"])
        if proposal.get("recommendation") == "approve_review_pending_keyframes":
            answer = (
                f"我看到{labels}关键帧是规则审查待确认，不是生成失败。"
                f"建议按默认方案处理：{proposal['default_instruction']}。"
                "如果确认，请回复“好，执行吧”，我会先标记这些关键帧为已确认，再进入视频生成。"
            )
        else:
            answer = (
                f"我看到{labels}关键帧审查未通过，主要问题是参考资产不完整。"
                f"建议按默认修复方案处理：{proposal['default_instruction']}。"
                "如果确认，请回复“好，执行吧”，我会只重生成这些审查失败的关键帧，原已选图片会保留在候选/历史里。"
            )
    else:
        answer = "当前关键帧审查没有通过，但我还不能直接重做。请说明要重做哪些镜头，以及具体怎么改（例如构图、风格、人物/场景、内容调整）。我拿到这些信息后再派发关键帧生成。"
    planner = routing.get("planner") if isinstance(routing.get("planner"), dict) else {}
    next_planner = {
        **planner,
        "action": "generate_keyframes",
        "intent_type": "production_action",
        "dispatch_ready": False,
        "reply": answer,
        "reason": "keyframe_review_blocker_repair_requires_confirmation" if proposal else "keyframe_review_blocker_requires_revision_details",
        "missing_info": ["确认默认修复方案"] if proposal else ["要重做的镜头编号或范围", "具体修改要求"],
    }
    next_routing = {
        **routing,
        "resolved_action": "",
        "routing_source": "review_blocker_clarification",
        "intent_type": "production_action",
        "action_ceiling": "needs_confirmation",
        "utterance_type": "confirm_required",
        "planner": next_planner,
        "review_blocker_clarification": {
            "missing": missing,
            "reason": gate.get("reason") or next_action.get("reason") or "",
            "required": ["confirm_default_repair"] if proposal else ["shot_scope", "revision_instruction"],
        },
    }
    if proposal:
        pending_action = {
            **proposal,
            "status": "awaiting_confirmation",
            "domain": "video" if proposal.get("action") == "generate_videos" else "keyframe",
            "target_domain": "video" if proposal.get("action") == "generate_videos" else "keyframe",
            "instruction": instruction,
            "continue_body": _followup_continue_body({}, routing={**next_routing, "resolved_action": proposal["action"]}, action=proposal["action"]),
            "routing": {**next_routing, "resolved_action": proposal["action"], "pending_confirmation": True},
        }
        next_routing["pending_action"] = pending_action
        next_routing["review_blocker_clarification"]["proposal"] = proposal
        await _save_pending_action(
            db,
            run_id=run_id,
            user_id=user_id,
            pending_action=pending_action,
            current_goal=instruction,
            routing=next_routing,
            answer=answer,
        )
    next_routing.pop("state_machine_recovery", None)
    next_routing.pop("controller_intent", None)
    next_routing.pop("control_tool", None)
    next_body = {**continue_body, "human_routing": next_routing}
    next_body.pop("action", None)
    next_body.pop("continue_action", None)
    return next_body, next_routing


async def _apply_video_review_blocker_clarification_routing(
    db: AsyncSession,
    continue_body: dict[str, Any],
    routing: dict[str, Any],
    *,
    run_id: str,
    project_id: str,
    user_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if routing.get("routing_source") == "pending_action_confirm" or routing.get("explicit_action"):
        return continue_body, routing
    action = str(routing.get("resolved_action") or continue_body.get("action") or "").strip()
    if action != "plan_final_edit":
        return continue_body, routing

    state = await _run_production_state(db, run_id=run_id, project_id=project_id, user_id=user_id)
    gate = evaluate_action_gate(
        "plan_final_edit",
        shots=state["shots"],
        tasks=state["tasks"],
        production_run=state["production_run"],
    )
    missing = [str(item) for item in gate.get("missing") or []]
    if "video_review_blockers" not in set(missing):
        return continue_body, routing

    proposal = _build_video_review_repair_proposal(state["shots"])
    if not proposal:
        return continue_body, routing

    labels = _format_shot_indices(proposal["shot_indices"])
    if proposal.get("recommendation") == "approve_review_pending_videos":
        answer = (
            f"我看到{labels}视频片段是规则审查待确认，不是生成失败。"
            f"建议按默认方案处理：{proposal['default_instruction']}。"
            "如果确认，请回复“好，执行吧”，我会先标记这些视频为已确认，再进入剪辑成片。"
        )
    else:
        answer = (
            f"我看到{labels}视频审查未通过。"
            f"建议按默认修复方案处理：{proposal['default_instruction']}。"
            "如果确认，请回复“好，执行吧”，我会先重生成这些视频片段。"
        )

    planner = routing.get("planner") if isinstance(routing.get("planner"), dict) else {}
    next_planner = {
        **planner,
        "action": "plan_final_edit",
        "intent_type": "production_action",
        "dispatch_ready": False,
        "reply": answer,
        "reason": "video_review_blocker_repair_requires_confirmation",
        "missing_info": ["确认默认修复方案"],
    }
    next_routing = {
        **routing,
        "resolved_action": "",
        "routing_source": "video_review_blocker_clarification",
        "intent_type": "production_action",
        "action_ceiling": "needs_confirmation",
        "utterance_type": "confirm_required",
        "planner": next_planner,
        "video_review_blocker_clarification": {
            "missing": missing,
            "reason": gate.get("reason") or "",
            "required": ["confirm_default_repair"],
            "proposal": proposal,
        },
    }
    pending_action = {
        **proposal,
        "status": "awaiting_confirmation",
        "domain": "final_edit" if proposal.get("action") == "plan_final_edit" else "video",
        "target_domain": "final_edit" if proposal.get("action") == "plan_final_edit" else "video",
        "instruction": str(routing.get("instruction") or ""),
        "continue_body": _followup_continue_body({}, routing={**next_routing, "resolved_action": proposal["action"]}, action=proposal["action"]),
        "routing": {**next_routing, "resolved_action": proposal["action"], "pending_confirmation": True},
    }
    next_routing["pending_action"] = pending_action
    await _save_pending_action(
        db,
        run_id=run_id,
        user_id=user_id,
        pending_action=pending_action,
        current_goal=str(routing.get("instruction") or ""),
        routing=next_routing,
        answer=answer,
    )
    next_routing.pop("state_machine_recovery", None)
    next_routing.pop("controller_intent", None)
    next_routing.pop("control_tool", None)
    next_body = {**continue_body, "human_routing": next_routing}
    next_body.pop("action", None)
    next_body.pop("continue_action", None)
    return next_body, next_routing


def _is_keyframe_review_repair_intent(routing: dict[str, Any], continue_body: dict[str, Any]) -> bool:
    planner = routing.get("planner") if isinstance(routing.get("planner"), dict) else {}
    intent = routing.get("intent") if isinstance(routing.get("intent"), dict) else {}
    action_values = {
        str(planner.get("action") or "").strip(),
        str(intent.get("action") or "").strip(),
        str(continue_body.get("action") or "").strip(),
        str(routing.get("action_hint") or "").strip(),
    }
    if "generate_keyframes" in action_values:
        return True
    instruction = str(routing.get("instruction") or "").strip().lower()
    if str(routing.get("target_domain") or "") == "keyframe" and _has_continue_or_keyframe_terms(instruction):
        return True
    return _is_generic_continue_instruction(instruction)


def _has_continue_or_keyframe_terms(instruction: str) -> bool:
    return any(
        token in instruction
        for token in (
            "continue",
            "继续",
            "繼續",
            "执行",
            "執行",
            "生成",
            "重做",
            "修复",
            "修復",
            "keyframe",
            "关键帧",
            "關鍵幀",
            "首帧",
            "首幀",
            "出图",
            "出圖",
        )
    )


def _is_generic_continue_instruction(instruction: str) -> bool:
    text = instruction.strip().lower()
    return text in {"continue", "继续", "繼續", "继续执行", "繼續執行", "好，执行吧", "好的，执行吧", "执行吧"}


def _build_keyframe_review_repair_proposal(shots: list[dict[str, Any]]) -> dict[str, Any] | None:
    blocked: list[dict[str, Any]] = []
    missing_by_shot: dict[int, list[str]] = {}
    for shot in shots:
        status = _image_review_status(shot)
        if status not in {"needs_review", "regenerate", "failed", "fail", "rejected", "blocked"}:
            continue
        try:
            shot_index = int(shot.get("shot_index") or 0)
        except (TypeError, ValueError):
            shot_index = 0
        if shot_index <= 0:
            continue
        blocked.append(shot)
        missing = _missing_reference_assets_from_review(shot)
        if missing:
            missing_by_shot[shot_index] = missing
    if not blocked:
        return None
    shot_indices = [int(shot.get("shot_index") or 0) for shot in blocked]
    statuses = {_image_review_status(shot) for shot in blocked}
    if statuses == {"needs_review"}:
        return {
            "action": "generate_videos",
            "recommendation": "approve_review_pending_keyframes",
            "shot_indices": shot_indices,
            "reason": "image_review_needs_human_approval",
            "default_instruction": f"人工确认{_format_shot_indices(shot_indices)}当前关键帧可作为视频首帧，标记为 approved 后进入视频生成",
            "requires_confirmation": True,
            "missing_reference_assets_by_shot": missing_by_shot,
        }
    all_missing = {item for values in missing_by_shot.values() for item in values}
    fixes: list[str] = []
    if "character" in all_missing:
        fixes.append("补齐角色参考")
    if "scene" in all_missing:
        fixes.append("补齐场景参考")
    if "prop" in all_missing:
        fixes.append("补齐道具参考")
    if not fixes:
        fixes.append("按审查意见补齐缺失参考")
    default_instruction = (
        f"针对{_format_shot_indices(shot_indices)}，"
        f"{'、'.join(fixes)}，并在保留原分镜意图、人物设定和镜头叙事的前提下重生成更稳定的关键帧"
    )
    return {
        "action": "generate_keyframes",
        "recommendation": "regenerate_review_failed_keyframes",
        "shot_indices": shot_indices,
        "reason": "image_review_blockers",
        "default_instruction": default_instruction,
        "requires_confirmation": True,
        "missing_reference_assets_by_shot": missing_by_shot,
    }


def _build_video_review_repair_proposal(shots: list[dict[str, Any]]) -> dict[str, Any] | None:
    blocked: list[dict[str, Any]] = []
    for shot in shots:
        status = _video_review_status(shot)
        if status not in {"needs_review", "regenerate", "failed", "fail", "rejected", "blocked"}:
            continue
        try:
            shot_index = int(shot.get("shot_index") or 0)
        except (TypeError, ValueError):
            shot_index = 0
        if shot_index > 0:
            blocked.append(shot)
    if not blocked:
        return None
    shot_indices = [int(shot.get("shot_index") or 0) for shot in blocked]
    statuses = {_video_review_status(shot) for shot in blocked}
    if statuses == {"needs_review"}:
        return {
            "action": "plan_final_edit",
            "recommendation": "approve_review_pending_videos",
            "shot_indices": shot_indices,
            "reason": "video_review_needs_human_approval",
            "default_instruction": f"人工确认{_format_shot_indices(shot_indices)}当前视频片段可进入剪辑，标记为 approved 后进入剪辑成片",
            "requires_confirmation": True,
        }
    return {
        "action": "generate_videos",
        "recommendation": "regenerate_review_failed_videos",
        "shot_indices": shot_indices,
        "reason": "video_review_blockers",
        "default_instruction": f"针对{_format_shot_indices(shot_indices)}重生成视频片段，并保留原关键帧、分镜意图和镜头运动约束",
        "requires_confirmation": True,
    }


def _image_review_status(shot: dict[str, Any]) -> str:
    selected = str(shot.get("selected_image") or "").strip()
    candidates = shot.get("image_candidates")
    values = candidates if isinstance(candidates, list) else [candidates] if candidates else []
    fallback = ""
    for candidate in values:
        if not isinstance(candidate, dict):
            continue
        review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
        status = str(candidate.get("review_status") or candidate.get("status") or review.get("status") or "").strip().lower()
        if not status:
            continue
        url = str(candidate.get("url") or candidate.get("uri") or candidate.get("image_url") or "").strip()
        if selected and url == selected:
            return status
        fallback = fallback or status
    return fallback


def _video_review_status(shot: dict[str, Any]) -> str:
    selected = str(shot.get("selected_video") or "").strip()
    candidates = shot.get("video_variants")
    values = candidates if isinstance(candidates, list) else [candidates] if candidates else []
    fallback = ""
    for candidate in values:
        if not isinstance(candidate, dict):
            continue
        review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
        status = str(candidate.get("review_status") or candidate.get("status") or review.get("status") or "").strip().lower()
        if not status:
            continue
        url = str(candidate.get("url") or candidate.get("uri") or candidate.get("video_url") or "").strip()
        if selected and url == selected:
            return status
        fallback = fallback or status
    return fallback


def _missing_reference_assets_from_review(shot: dict[str, Any]) -> list[str]:
    aliases = {"character": "character", "role": "character", "scene": "scene", "background": "scene", "prop": "prop"}
    found: list[str] = []
    candidates = shot.get("image_candidates")
    values = candidates if isinstance(candidates, list) else [candidates] if candidates else []
    for candidate in values:
        if not isinstance(candidate, dict):
            continue
        review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
        raw_assets = review.get("missing_reference_assets") or candidate.get("missing_reference_assets") or []
        if isinstance(raw_assets, str):
            raw_assets = [raw_assets]
        for item in raw_assets if isinstance(raw_assets, list) else []:
            key = aliases.get(str(item).strip().lower())
            if key and key not in found:
                found.append(key)
        notes = review.get("notes") or candidate.get("notes") or []
        if isinstance(notes, str):
            notes = [notes]
        text_blob = " ".join(str(note).lower() for note in notes if note)
        text_hits = sorted(
            (text_blob.find(token), key)
            for token, key in aliases.items()
            if token in text_blob
        )
        for _, key in text_hits:
            if key not in found:
                found.append(key)
    return found


def _format_shot_indices(indices: list[int]) -> str:
    cleaned = [int(item) for item in indices if int(item or 0) > 0]
    if not cleaned:
        return "相关镜头"
    return "第" + "、".join(str(item) for item in cleaned) + "镜"


def _has_keyframe_revision_details(instruction: str) -> bool:
    text = str(instruction or "").strip().lower()
    if not text:
        return False
    has_scope = bool(re.search(r"(第\s*\d+\s*[镜鏡]|第\s*[一二三四五六七八九十]+\s*[镜鏡]|\bshot\s*\d+\b|全部|所有|全都|每个|每個)", text))
    has_change = any(
        token in text
        for token in (
            "改成",
            "换成",
            "變成",
            "变成",
            "风格",
            "風格",
            "构图",
            "構圖",
            "内容",
            "內容",
            "人物",
            "场景",
            "場景",
            "颜色",
            "顏色",
            "不要",
            "去掉",
            "增加",
            "保留",
            "过暗",
            "過暗",
            "不像",
            "崩",
            "错",
            "錯",
        )
    )
    return has_scope and has_change


def _apply_pending_action_confirmation(
    continue_body: dict[str, Any],
    routing: dict[str, Any],
    pending_action: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    action = str(pending_action.get("action") or "").strip()
    if not action:
        return continue_body, routing
    next_routing = {
        **routing,
        "resolved_action": action,
        "routing_source": "pending_action_confirm",
        "intent_type": "production_action",
        "action_ceiling": "execute_allowed",
        "utterance_type": "confirm",
        "pending_action": pending_action,
        "target_domain": str(pending_action.get("domain") or classify_target_domain(str(routing.get("instruction") or ""), action=action)),
    }
    saved_body = pending_action.get("continue_body") if isinstance(pending_action.get("continue_body"), dict) else {}
    next_body = {
        **saved_body,
        **continue_body,
        "action": action,
        "continue_action": action,
        "human_routing": next_routing,
    }
    return next_body, next_routing


async def _approve_review_pending_keyframes_for_routing(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    routing: dict[str, Any],
) -> None:
    if str(routing.get("resolved_action") or "") != "generate_videos":
        return
    pending = routing.get("pending_action") if isinstance(routing.get("pending_action"), dict) else {}
    if str(pending.get("recommendation") or "") != "approve_review_pending_keyframes":
        return
    shot_indices = []
    for item in pending.get("shot_indices") or []:
        try:
            shot_index = int(item)
        except (TypeError, ValueError):
            continue
        if shot_index > 0:
            shot_indices.append(shot_index)
    await _approve_review_pending_keyframes(db, project_id=project_id, user_id=user_id, shot_indices=shot_indices)


async def _approve_review_pending_videos_for_routing(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    routing: dict[str, Any],
) -> None:
    if str(routing.get("resolved_action") or "") != "plan_final_edit":
        return
    pending = routing.get("pending_action") if isinstance(routing.get("pending_action"), dict) else {}
    if str(pending.get("recommendation") or "") != "approve_review_pending_videos":
        return
    shot_indices = []
    for item in pending.get("shot_indices") or []:
        try:
            shot_index = int(item)
        except (TypeError, ValueError):
            continue
        if shot_index > 0:
            shot_indices.append(shot_index)
    await _approve_review_pending_videos(db, project_id=project_id, user_id=user_id, shot_indices=shot_indices)


async def _approve_review_pending_keyframes(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    shot_indices: list[int],
) -> None:
    filters = ["project_id = :project_id", "user_id = :user_id", "selected_image IS NOT NULL", "selected_image <> ''"]
    params: dict[str, Any] = {"project_id": project_id, "user_id": user_id}
    if shot_indices:
        filters.append("shot_index IN :shot_indices")
        params["shot_indices"] = tuple(shot_indices)
    result = await db.execute(
        text(
            f"""
            SELECT shot_index, selected_image, image_candidates_json
            FROM shot_rows
            WHERE {' AND '.join(filters)}
            ORDER BY shot_index ASC
            """
        ).bindparams(bindparam("shot_indices", expanding=True)) if shot_indices else text(
            f"""
            SELECT shot_index, selected_image, image_candidates_json
            FROM shot_rows
            WHERE {' AND '.join(filters)}
            ORDER BY shot_index ASC
            """
        ),
        params,
    )
    for row in result.mappings().all():
        selected = str(row.get("selected_image") or "").strip()
        candidates = _mark_selected_keyframe_candidate_review_approved(
            row.get("image_candidates_json") if isinstance(row.get("image_candidates_json"), list) else [],
            selected,
            approved_by="human_continue",
        )
        await db.execute(
            text(
                """
                UPDATE shot_rows
                SET image_candidates_json = CAST(:image_candidates_json AS JSONB),
                    status = CASE WHEN status = 'pending' THEN 'image_done' ELSE status END,
                    updated_at = NOW()
                WHERE project_id = :project_id
                  AND user_id = :user_id
                  AND shot_index = :shot_index
                """
            ),
            {
                "project_id": project_id,
                "user_id": user_id,
                "shot_index": int(row["shot_index"]),
                "image_candidates_json": json.dumps(candidates, ensure_ascii=False, default=str),
            },
        )


async def _approve_review_pending_videos(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    shot_indices: list[int],
) -> None:
    filters = ["project_id = :project_id", "user_id = :user_id", "selected_video IS NOT NULL", "selected_video <> ''"]
    params: dict[str, Any] = {"project_id": project_id, "user_id": user_id}
    if shot_indices:
        filters.append("shot_index IN :shot_indices")
        params["shot_indices"] = tuple(shot_indices)
    result = await db.execute(
        text(
            f"""
            SELECT shot_index, selected_video, video_variants_json
            FROM shot_rows
            WHERE {' AND '.join(filters)}
            ORDER BY shot_index ASC
            """
        ).bindparams(bindparam("shot_indices", expanding=True)) if shot_indices else text(
            f"""
            SELECT shot_index, selected_video, video_variants_json
            FROM shot_rows
            WHERE {' AND '.join(filters)}
            ORDER BY shot_index ASC
            """
        ),
        params,
    )
    for row in result.mappings().all():
        selected = str(row.get("selected_video") or "").strip()
        variants = _mark_selected_keyframe_candidate_review_approved(
            row.get("video_variants_json") if isinstance(row.get("video_variants_json"), list) else [],
            selected,
            approved_by="human_continue",
        )
        await db.execute(
            text(
                """
                UPDATE shot_rows
                SET video_variants_json = CAST(:video_variants_json AS JSONB),
                    status = CASE WHEN status IN ('pending', 'image_done') THEN 'video_done' ELSE status END,
                    updated_at = NOW()
                WHERE project_id = :project_id
                  AND user_id = :user_id
                  AND shot_index = :shot_index
                """
            ),
            {
                "project_id": project_id,
                "user_id": user_id,
                "shot_index": int(row["shot_index"]),
                "video_variants_json": json.dumps(variants, ensure_ascii=False, default=str),
            },
        )


def _should_confirm_pending_action(routing: dict[str, Any]) -> bool:
    if routing.get("explicit_action"):
        return False
    if routing.get("action_ceiling") == "pending_confirm":
        return True
    text = str(routing.get("instruction") or "").strip().lower()
    normalized = re.sub(r"[\s,，。.!！?？]+", "", text)
    return normalized in {
        "嗯",
        "嗯嗯",
        "好",
        "好的",
        "可以",
        "确认",
        "確認",
        "对",
        "對",
        "是",
        "执行",
        "執行",
        "执行吧",
        "執行吧",
        "继续",
        "繼續",
        "继续执行",
        "繼續執行",
        "继续吧",
        "繼續吧",
        "ok",
        "yes",
    }


def _should_preserve_planner_final_edit(routing: dict[str, Any]) -> bool:
    planner = routing.get("planner") if isinstance(routing.get("planner"), dict) else {}
    if not planner:
        return False
    action = str(planner.get("action") or routing.get("resolved_action") or "")
    if action != "plan_final_edit" or not bool(planner.get("dispatch_ready")):
        return False
    if _safe_float(planner.get("confidence")) < 0.6:
        return False
    return _has_final_edit_terms(str(routing.get("instruction") or ""))


def _has_final_edit_terms(instruction: str) -> bool:
    text = str(instruction or "").strip().lower()
    return any(
        term in text
        for term in ("剪辑", "剪輯", "成片", "导出", "導出", "配音", "字幕", "音乐", "音樂", "bgm", "final cut", "export")
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def _recent_human_dialogue_context(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
) -> list[dict[str, Any]]:
    try:
        events = await list_project_agent_events(
            db,
            project_id=project_id,
            user_id=user_id,
            run_id=run_id,
            limit=12,
        )
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for event in events:
        phase = str(event.get("phase") or "")
        if phase not in {"human_instruction", "human_response", "llm_planner"}:
            continue
        meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
        planner = meta.get("planner") if isinstance(meta.get("planner"), dict) else {}
        items.append(
            {
                "phase": phase,
                "summary": str(event.get("summary") or ""),
                "detail": str(event.get("detail") or ""),
                "instruction": str(meta.get("instruction") or ""),
                "answer": str(meta.get("answer") or ""),
                "intent_type": str(planner.get("intent_type") or meta.get("intent_type") or ""),
                "dispatch_ready": planner.get("dispatch_ready"),
                "missing_info": planner.get("missing_info") or [],
                "extracted": planner.get("extracted") or {},
            }
        )
    return items


async def _build_control_diagnostics(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: int,
    routing: dict[str, Any],
) -> dict[str, Any]:
    snapshot = await get_agent_run_snapshot(
        db,
        run_id=run_id,
        user_id=user_id,
        event_limit=80,
        task_limit=120,
        artifact_limit=120,
        evidence_item_limit=20,
        stream_limit=40,
    )
    tool_name = str((routing.get("control_tool") or {}).get("tool_name") or "")
    if not tool_name and str(routing.get("intent_type") or "") == "ui_diagnostic":
        tool_name = "diagnose_outputs"
    if tool_name == "diagnose_tasks":
        return {"diagnose_tasks": diagnose_tasks_from_snapshot(snapshot)}
    if tool_name == "diagnose_provider_writeback":
        return {"diagnose_provider_writeback": diagnose_provider_writeback_from_snapshot(snapshot)}
    if tool_name == "diagnose_script":
        return {"diagnose_script": diagnose_script_from_snapshot(snapshot, instruction=str(routing.get("instruction") or ""))}
    if tool_name == "diagnose_keyframe_pool":
        return {"diagnose_keyframe_pool": diagnose_keyframe_pool_from_snapshot(snapshot, instruction=str(routing.get("instruction") or ""))}
    return {"outputs": diagnose_outputs_from_snapshot(snapshot)}


def _needs_control_diagnostics(routing: dict[str, Any]) -> bool:
    tool_name = str((routing.get("control_tool") or {}).get("tool_name") or "")
    return str(routing.get("intent_type") or "") == "ui_diagnostic" or is_control_diagnostic_tool(tool_name)


async def _compose_answer_from_evidence(
    *,
    instruction: str,
    fallback_answer: str,
    diagnostics: dict[str, Any] | None,
    routing: dict[str, Any],
    recent_human_events: list[dict[str, Any]],
    user_id: int | None = None,
) -> dict[str, Any] | None:
    if not diagnostics:
        return None
    tool_result = _primary_tool_result(diagnostics, routing=routing)
    if not tool_result:
        return None
    composition = await compose_evidence_reply(
        instruction=instruction,
        tool_result=tool_result,
        fallback_reply=fallback_answer,
        allowed_actions=_allowed_composer_actions(tool_result),
        gate={},
        recent_human_events=recent_human_events,
        user_id=user_id,
    )
    return composition.as_dict() if composition else None


def _primary_tool_result(diagnostics: dict[str, Any], *, routing: dict[str, Any]) -> dict[str, Any]:
    tool_name = str((routing.get("control_tool") or {}).get("tool_name") or "")
    if tool_name and isinstance(diagnostics.get(tool_name), dict):
        return diagnostics[tool_name]
    if isinstance(diagnostics.get("outputs"), dict):
        return diagnostics["outputs"]
    for value in diagnostics.values():
        if isinstance(value, dict):
            return value
    return {}


def _allowed_composer_actions(tool_result: dict[str, Any]) -> list[str]:
    recommended = str(tool_result.get("recommended_action") or "").strip()
    tool_name = str(tool_result.get("tool_name") or "")
    return allowed_recommendations_for_tool(tool_name, recommended=recommended)


async def _production_stage_fallback_action(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: int,
) -> str:
    """Find the next pending production stage action when diagnostic finds no issue."""
    try:
        from app.services.agent_run_state_machine import evaluate_production_stages
        from app.services.agent_run_snapshot import get_agent_run_snapshot
        snapshot = await get_agent_run_snapshot(db, run_id=run_id, user_id=user_id)
        if not snapshot:
            return ""
        outputs = snapshot.get("outputs") if isinstance(snapshot.get("outputs"), dict) else {}
        shots = list(outputs.get("shots") or snapshot.get("ledger", {}).get("shots") or [])
        tasks = list(snapshot.get("tasks") or [])
        run_data = snapshot.get("run") if isinstance(snapshot.get("run"), dict) else {}
        production_run = {
            "status": run_data.get("status", ""),
            "current_stage": run_data.get("current_phase", ""),
            "final_video_url": str(
                (outputs.get("production_run") or {}).get("final_video_url")
                or (outputs.get("summary") or {}).get("final_video_url")
                or ""
            ).strip(),
        }
        stages = evaluate_production_stages(shots=shots, tasks=tasks, production_run=production_run)
        for row in stages:
            if row.get("status") in {"pending", "blocked"} and row.get("action"):
                action = str(row["action"])
                if action in {"generate_story_plan", "plan_visual_assets", "generate_keyframes", "generate_videos", "plan_final_edit"}:
                    return action
        return ""
    except Exception:
        return ""


def _followup_action_from_evidence(
    *,
    composer: dict[str, Any] | None,
    diagnostics: dict[str, Any],
    routing: dict[str, Any] | None = None,
) -> str:
    recommended = str((composer or {}).get("recommended_action") or "").strip()
    if not recommended:
        primary = next((value for value in diagnostics.values() if isinstance(value, dict)), {})
        recommended = str(primary.get("recommended_action") or "").strip()
    followup_action = followup_action_for_recommendation(recommended)
    if followup_action and not _recommendation_matches_target_domain(recommended, followup_action, routing):
        return ""
    if _action_ceiling(routing) == "inspect_only" and followup_action:
        return ""
    if _is_final_edit_status_context(routing) and followup_action == "generate_keyframes":
        return ""
    return followup_action


_DIAGNOSTIC_REPAIR_RECOMMENDATIONS = {
    "repair_missing_images",
    "repair_missing_videos",
    "retry_failed_keyframes",
    "retry_failed_videos",
    "repair_keyframe_pool",
    "refresh_asset_urls",
    "generate_keyframe_batch",
    "revise_story_plan",
    "revise_director_notes",
    "revise_shots",
}


def _pending_action_from_evidence(
    *,
    composer: dict[str, Any] | None,
    diagnostics: dict[str, Any],
    routing: dict[str, Any],
    instruction: str,
) -> dict[str, Any] | None:
    recommended = str((composer or {}).get("recommended_action") or "").strip()
    if not recommended:
        primary = next((value for value in diagnostics.values() if isinstance(value, dict)), {})
        recommended = str(primary.get("recommended_action") or "").strip()
    action = followup_action_for_recommendation(recommended)
    if not action:
        return None
    if not _recommendation_can_be_pending_for_target_domain(recommended, action, routing):
        return None
    if _action_ceiling(routing) != "inspect_only":
        return None
    domain = domain_for_action(action) or domain_for_recommendation(recommended)
    return {
        "status": "awaiting_confirmation",
        "action": action,
        "recommendation": recommended,
        "domain": domain,
        "target_domain": str(routing.get("target_domain") or ""),
        "instruction": instruction,
        "continue_body": _followup_continue_body({}, routing=routing, action=action),
        "routing": {**routing, "resolved_action": action, "pending_confirmation": True},
    }


def _build_decision_context(
    *,
    current_goal: str = "",
    routing: dict[str, Any] | None = None,
    pending_action: dict[str, Any] | None = None,
    answer: str = "",
    state_machine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    routing_payload = routing if isinstance(routing, dict) else {}
    state = state_machine if isinstance(state_machine, dict) else {}
    pending = _compact_pending_action(pending_action)
    blocked_by = [str(item) for item in (state.get("missing") or []) if str(item or "").strip()]
    return {
        "current_goal": str(current_goal or routing_payload.get("instruction") or "").strip(),
        "awaiting_user": "confirm" if pending else "",
        "pending_action": pending,
        "last_recommendation": str(answer or "").strip(),
        "blocked_by": blocked_by,
        "block_reason": str(state.get("reason") or "").strip(),
        "next_action": str((pending or {}).get("action") or state.get("next_action") or routing_payload.get("resolved_action") or "").strip(),
        "routing_source": str(routing_payload.get("routing_source") or "").strip(),
        "target_domain": str(routing_payload.get("target_domain") or "").strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _compact_pending_action(pending_action: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(pending_action, dict) or not pending_action.get("action"):
        return None
    allowed = ("action", "recommendation", "domain", "target_domain", "status", "instruction")
    compact = {
        key: pending_action.get(key)
        for key in allowed
        if pending_action.get(key) not in (None, "", [], {})
    }
    return compact if compact.get("action") else None


def _recommendation_matches_target_domain(recommendation: str, action: str, routing: dict[str, Any] | None) -> bool:
    if not isinstance(routing, dict):
        return True
    target_domain = str(routing.get("target_domain") or "").strip()
    if not target_domain or target_domain in {"output", "task", "provider"}:
        return True
    recommendation_domain = domain_for_recommendation(recommendation) or domain_for_action(action)
    return not recommendation_domain or recommendation_domain == target_domain


def _recommendation_can_be_pending_for_target_domain(recommendation: str, action: str, routing: dict[str, Any] | None) -> bool:
    if _recommendation_matches_target_domain(recommendation, action, routing):
        return True
    if not isinstance(routing, dict):
        return True
    target_domain = str(routing.get("target_domain") or "").strip()
    recommendation_domain = domain_for_recommendation(recommendation) or domain_for_action(action)
    dependency_domains = {
        "final_edit": {"video"},
        "video": {"keyframe"},
    }
    return recommendation_domain in dependency_domains.get(target_domain, set())


def _action_ceiling(routing: dict[str, Any] | None) -> str:
    if not isinstance(routing, dict):
        return ""
    utterance = routing.get("utterance") if isinstance(routing.get("utterance"), dict) else {}
    return str(routing.get("action_ceiling") or utterance.get("action_ceiling") or "")


def _merge_pending_action_answer(answer: str, pending_action: dict[str, Any]) -> str:
    label = _action_display_name(str(pending_action.get("action") or ""))
    message = f"我不会自动执行；如需继续，请回复“好，执行吧”，我会按当前证据执行{label}。"
    return _merge_actionable_answer(answer, message)


def _is_final_edit_status_context(routing: dict[str, Any] | None) -> bool:
    if not isinstance(routing, dict):
        return False
    instruction = str(routing.get("instruction") or "")
    if not _has_final_edit_terms(instruction):
        return False
    action = str(routing.get("resolved_action") or "")
    intent_type = str(routing.get("intent_type") or "")
    tool_name = str((routing.get("control_tool") or {}).get("tool_name") or "")
    return action == "status_query" or intent_type in {"ui_diagnostic", "status_query"} or tool_name == "diagnose_outputs"


def _followup_continue_body(
    continue_body: dict[str, Any],
    *,
    routing: dict[str, Any],
    action: str,
) -> dict[str, Any]:
    verification_plan = build_verification_plan(action)
    next_routing = {
        **routing,
        "resolved_action": action,
        "routing_source": "control_tool_followup",
        "followup_from_tool": True,
        "verification_plan": verification_plan,
    }
    return {
        **continue_body,
        "action": action,
        "continue_action": action,
        "human_routing": next_routing,
        "verification_plan": verification_plan,
    }


def _merge_actionable_answer(answer: str, action_message: str) -> str:
    base = str(answer or "").strip()
    message = str(action_message or "").strip()
    if not message:
        return base
    if not base:
        return message
    if message in base:
        return base
    # If the model ended with a choice question but the controller has a safe
    # deterministic action, make the controller decision explicit instead of
    # leaving the user with a false choice.
    if base.endswith(("?", "？")):
        return f"{base} 中控已根据证据选择可恢复动作：{message}"
    return f"{base}{message}"


def _is_human_status_query(instruction: str) -> bool:
    text_value = str(instruction or "").strip().lower()
    if not text_value:
        return False
    keywords = (
        "到哪一步",
        "哪一步",
        "进度",
        "進度",
        "现在做什么",
        "現在做什麼",
        "谁在管",
        "誰在管",
        "谁负责",
        "誰負責",
        "状态",
        "狀態",
        "怎么样了",
        "怎麼樣了",
        "看到了吗",
        "看到了嗎",
        "没显示",
        "沒有顯示",
        "不显示",
        "不顯示",
        "显示不了",
        "顯示不了",
        "破图",
        "破圖",
        "加载失败",
        "載入失敗",
        "what step",
        "progress",
        "status",
        "not showing",
        "not visible",
        "broken image",
    )
    return any(keyword in text_value for keyword in keywords)


def _human_instruction_summary(routing: dict[str, Any]) -> str:
    intent_type = str(routing.get("intent_type") or "")
    if intent_type == "ui_diagnostic":
        return "已接收成果区显示问题，正在检查快照和图片 URL。"
    if intent_type == "status_query" or routing.get("resolved_action") == "status_query":
        return "已接收状态查询，准备直接答复。"
    action = str(routing.get("resolved_action") or "").strip()
    if action:
        return f"已接收人工指令，准备处理{_action_display_name(action)}。"
    return "已接收人工输入，等待进一步判断。"


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


def _status_display_name(status: str) -> str:
    labels = {
        "queued": "已排队",
        "dispatching": "派发中",
        "running": "执行中",
        "processing": "处理中",
        "completed": "已完成",
        "failed": "失败",
        "deferred": "已暂存",
        "provider_waiting": "等待 provider",
    }
    return labels.get(str(status or "").strip(), str(status or "未知"))


def _answered_event_title(executor: str) -> str:
    if executor == "OutputDiagnosticExecutor":
        return "DeepSeek 检查成果区"
    if executor == "TaskDiagnosticExecutor":
        return "DeepSeek 检查任务队列"
    if executor == "ProviderWritebackDiagnosticExecutor":
        return "DeepSeek 检查写回链路"
    if executor == "ScriptDiagnosticExecutor":
        return "DeepSeek 检查剧本分镜"
    if executor == "KeyframePoolDiagnosticExecutor":
        return "DeepSeek 检查图片池"
    if executor == "StatusQueryExecutor":
        return "DeepSeek 答复当前状态"
    return "答复人工输入"


def _answered_event_reason(executor: str) -> str:
    if executor == "OutputDiagnosticExecutor":
        return "这属于成果显示诊断，先检查快照、写回字段和 URL 可访问性，不盲目重生。"
    if executor == "TaskDiagnosticExecutor":
        return "这属于任务队列诊断，先检查活动任务、失败任务和恢复动作。"
    if executor == "ProviderWritebackDiagnosticExecutor":
        return "这属于 provider 写回诊断，先检查任务结果和 shot_rows 写回字段。"
    if executor == "ScriptDiagnosticExecutor":
        return "这属于剧本/分镜处理，先读取当前剧本、分镜和导演建议证据，再决定答复或派发重写。"
    if executor == "KeyframePoolDiagnosticExecutor":
        return "这属于图片池处理，先读取候选图、已选主图、运行中任务和失败记录，再决定扩展、批量生成、选择或生成视频。"
    if executor == "StatusQueryExecutor":
        return "这属于状态查询，直接答复当前 run 和活动任务。"
    return "已根据当前上下文答复人工输入。"


async def _ensure_run_owner(db: AsyncSession, *, run_id: str, user_id: int) -> str:
    result = await db.execute(
        text(
            """
            SELECT r.project_id
            FROM agent_runs r
            JOIN projects p ON p.project_id = r.project_id AND p.user_id = r.user_id
            WHERE r.id = CAST(:run_id AS UUID)
              AND r.user_id = :user_id
            LIMIT 1
            """
        ),
        {"run_id": run_id, "user_id": user_id},
    )
    project_id = result.scalar_one_or_none()
    if project_id is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    return str(project_id)


async def _get_run_status(db: AsyncSession, *, run_id: str, user_id: int) -> str:
    result = await db.execute(
        text(
            """
            SELECT status
            FROM agent_runs
            WHERE id = CAST(:run_id AS UUID)
              AND user_id = :user_id
            LIMIT 1
            """
        ),
        {"run_id": run_id, "user_id": user_id},
    )
    status = result.scalar_one_or_none()
    if status is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    return str(status or "")


async def _load_pending_action(db: AsyncSession, *, run_id: str, user_id: int) -> dict[str, Any] | None:
    if not hasattr(db, "execute"):
        return None
    result = await db.execute(
        text(
            """
            SELECT meta->'pending_action' AS pending_action
            FROM agent_runs
            WHERE id = CAST(:run_id AS UUID)
              AND user_id = :user_id
            LIMIT 1
            """
        ),
        {"run_id": run_id, "user_id": user_id},
    )
    value = result.scalar_one_or_none()
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


async def _save_pending_action(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: int,
    pending_action: dict[str, Any],
    current_goal: str = "",
    routing: dict[str, Any] | None = None,
    answer: str = "",
    state_machine: dict[str, Any] | None = None,
) -> None:
    if not hasattr(db, "execute"):
        return
    decision_context = _build_decision_context(
        current_goal=current_goal,
        routing=routing,
        pending_action=pending_action,
        answer=answer,
        state_machine=state_machine,
    )
    await db.execute(
        text(
            """
            UPDATE agent_runs
            SET meta = jsonb_set(
                    jsonb_set(COALESCE(meta, '{}'::jsonb), '{pending_action}', CAST(:pending_action AS JSONB), true),
                    '{decision_context}',
                    CAST(:decision_context AS JSONB),
                    true
                ),
                updated_at = NOW()
            WHERE id = CAST(:run_id AS UUID)
              AND user_id = :user_id
            """
        ),
        {
            "run_id": run_id,
            "user_id": user_id,
            "pending_action": json.dumps(pending_action, ensure_ascii=False, default=str),
            "decision_context": json.dumps(decision_context, ensure_ascii=False, default=str),
        },
    )


async def _clear_pending_action(db: AsyncSession, *, run_id: str, user_id: int) -> None:
    if not hasattr(db, "execute"):
        return
    await db.execute(
        text(
            """
            UPDATE agent_runs
            SET meta = jsonb_set(
                    COALESCE(meta, '{}'::jsonb) - 'pending_action',
                    '{decision_context}',
                    jsonb_set(
                        jsonb_set(COALESCE(meta->'decision_context', '{}'::jsonb), '{pending_action}', 'null'::jsonb, true),
                        '{awaiting_user}',
                        '""'::jsonb,
                        true
                    ),
                    true
                ),
                updated_at = NOW()
            WHERE id = CAST(:run_id AS UUID)
              AND user_id = :user_id
            """
        ),
        {"run_id": run_id, "user_id": user_id},
    )


async def _user_id_from_stream_token(token: str) -> int:
    if not token:
        raise HTTPException(status_code=401, detail="missing token")
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="invalid token type")
        token_jti = get_token_jti(token, payload)
        if await is_token_blacklisted(token_jti):
            raise HTTPException(status_code=401, detail="token revoked")
        return int(payload["sub"])
    except HTTPException:
        raise
    except (JWTError, Exception):
        raise HTTPException(status_code=401, detail="invalid or expired token")


def _sse(event: str, data: dict[str, Any], *, event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    payload = json.dumps(data, ensure_ascii=False, default=str)
    for line in payload.splitlines() or ["{}"]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def _stream_history_order(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phase_rank = {
        "created": 0,
        "read_context": 10,
        "merge_memory": 20,
        "map_techniques": 30,
        "check_continuity": 40,
        "cost_guard": 50,
        "delivery_audit": 60,
        "dispatch_instruction": 70,
        "queued": 80,
        "worker_started": 90,
        "provider_requesting": 100,
        "provider_waiting": 110,
        "downloading": 120,
        "uploading": 130,
        "writing_back": 140,
        "writeback_review": 150,
        "completed": 160,
        "failed": 170,
        "blocked": 180,
        "cancelled": 190,
    }

    def key(event: dict[str, Any]) -> tuple[str, int, int, str]:
        progress = event.get("progress")
        return (
            str(event.get("created_at") or ""),
            phase_rank.get(str(event.get("phase") or ""), 999),
            int(progress) if isinstance(progress, int) else 999,
            str(event.get("id") or ""),
        )

    return sorted(events, key=key)


async def _get_run_status_for_update(db: AsyncSession, *, run_id: str, user_id: int) -> str:
    result = await db.execute(
        text(
            """
            SELECT status
            FROM agent_runs
            WHERE id = CAST(:run_id AS UUID)
              AND user_id = :user_id
            FOR UPDATE
            """
        ),
        {"run_id": run_id, "user_id": user_id},
    )
    status = result.scalar_one_or_none()
    if status is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    return str(status or "")


async def _ensure_run_can_dispatch(db: AsyncSession, *, run_id: str, user_id: int, action: str) -> None:
    status = await _get_run_status_for_update(db, run_id=run_id, user_id=user_id)
    if status == "cancelled":
        raise HTTPException(
            status_code=409,
            detail={"message": f"Cannot {action}; agent run is cancelled", "action": action, "run_id": run_id, "status": status},
        )
    if status == "completed":
        raise HTTPException(
            status_code=409,
            detail={"message": f"Cannot {action}; agent run is already completed", "action": action, "run_id": run_id, "status": status},
        )
    active = await _active_run_task_summary(db, run_id=run_id, user_id=user_id)
    if active["count"] > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Cannot {action}; agent run already has active tasks",
                "code": "active_tasks",
                "user_message": "当前已有任务正在执行，先等待任务完成或刷新成果区后再继续。",
                "action": action,
                "run_id": run_id,
                "active_task_count": active["count"],
                "active_task_ids": active["task_ids"],
                "active_task_statuses": active["statuses"],
                "active_tasks": active.get("items", []),
            },
        )


async def _ensure_action_gate_allows(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    action: str,
) -> None:
    state = await _run_production_state(db, run_id=run_id, project_id=project_id, user_id=user_id)
    gate = evaluate_action_gate(
        action,
        shots=state["shots"],
        tasks=state["tasks"],
        production_run=state["production_run"],
    )
    recovery_actions = _recovery_actions_for_gate(action, gate)
    if gate.get("allowed"):
        action_label = _action_display_name(action)
        await publish_agent_event(
            db,
            run_id=run_id,
            project_id=project_id,
            user_id=user_id,
            source="state_machine",
            event_type="decision",
            phase="state_machine_gate",
            title="状态机允许执行",
            detail=f"状态机允许进入{action_label}。",
            status="done",
            progress=None,
            meta={"gate": gate, "action": action, "available_actions": [action], "recovery_actions": []},
            actor="state_machine",
            event_kind="decision",
            visibility="expert",
            summary=f"状态机允许{action_label}",
            reason="前置产物和流程顺序满足当前动作要求。",
            debug={"gate": gate, "state": state},
        )
        await db.commit()
        return
    action_label = _action_display_name(action)
    await publish_agent_event(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        source="state_machine",
        event_type="risk",
        phase="state_machine_gate",
        title="状态机阻止越级执行",
        detail=str(gate.get("reason") or "Action is blocked by production order."),
        status="blocked",
        progress=None,
        meta={"gate": gate, "action": action, "missing": gate.get("missing") or [], "available_actions": recovery_actions, "recovery_actions": recovery_actions},
        actor="state_machine",
        event_kind="guardrail",
        visibility="user",
        summary=f"状态机阻止{action_label}越级执行",
        reason=str(gate.get("reason") or "缺少前置生产环节。"),
        debug={"gate": gate},
    )
    await db.commit()
    raise HTTPException(
        status_code=409,
        detail={
            "message": "Action blocked by production state machine",
            "action": action,
            "run_id": run_id,
            "stage_id": gate.get("stage_id"),
            "missing": gate.get("missing") or [],
            "reason": gate.get("reason") or "",
            "recovery": gate.get("recovery") or "",
            "available_actions": recovery_actions,
            "recovery_actions": recovery_actions,
        },
    )


def _recovery_actions_for_gate(action: str, gate: dict[str, Any]) -> list[str]:
    missing = set(str(item) for item in gate.get("missing") or [])
    if "selected_image" in missing:
        return ["plan_visual_assets", "generate_keyframes", "retry_later"]
    if "shot_rows" in missing or "generate_story_plan" in missing:
        return ["generate_story_plan", "ask_human"]
    if "selected_video" in missing:
        return ["generate_videos", "change_provider", "skip_shot"]
    if "image_review_blockers" in missing:
        return ["generate_keyframes", "ask_human"]
    if "video_review_blockers" in missing:
        return ["generate_videos", "ask_human"]
    if "image_task_failures" in missing:
        return ["retry_failed", "regenerate_reference", "ask_human"]
    if "video_task_failures" in missing:
        return ["retry_failed", "change_provider", "export_partial"]
    if action == "status_query":
        return ["answer_status_only"]
    return ["retry_later", "ask_human"]


async def _run_production_state(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
) -> dict[str, Any]:
    shots_result = await db.execute(
        text(
            """
            SELECT shot_index, prompt, selected_image, selected_video, status,
                   image_candidates_json AS image_candidates,
                   video_variants_json AS video_variants
            FROM shot_rows
            WHERE project_id = :project_id AND user_id = :user_id
            ORDER BY shot_index ASC
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    tasks_result = await db.execute(
        text(
            """
            SELECT task_id::text AS task_id, task_type, status, progress, payload, result
            FROM tasks
            WHERE run_id = CAST(:run_id AS UUID) AND user_id = :user_id
            ORDER BY created_at ASC
            """
        ),
        {"run_id": run_id, "user_id": user_id},
    )
    production_result = await db.execute(
        text(
            """
            SELECT status, current_stage, final_video_url
            FROM video_production_runs
            WHERE agent_run_id = CAST(:run_id AS UUID) AND user_id = :user_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"run_id": run_id, "user_id": user_id},
    )
    production_row = production_result.mappings().first()
    return {
        "shots": [dict(row) for row in shots_result.mappings().all()],
        "tasks": [dict(row) for row in tasks_result.mappings().all()],
        "production_run": dict(production_row) if production_row else None,
    }


async def _active_run_task_summary(db: AsyncSession, *, run_id: str, user_id: int) -> dict[str, Any]:
    query = text(
        """
        SELECT
            task_id::text AS task_id,
            task_type,
            status,
            progress,
            stage_text,
            payload,
            created_at,
            updated_at
        FROM tasks
        WHERE run_id = CAST(:run_id AS UUID)
          AND user_id = :user_id
          AND status IN :active_statuses
        ORDER BY created_at DESC
        LIMIT 20
        """
    ).bindparams(bindparam("active_statuses", expanding=True))
    result = await db.execute(query, {"run_id": run_id, "user_id": user_id, "active_statuses": ACTIVE_TASK_STATUSES})
    rows = result.mappings().all()
    items = [_normalize_active_task(row) for row in rows]
    return {
        "count": len(items),
        "task_ids": [item["task_id"] for item in items],
        "statuses": [item["status"] for item in items],
        "items": items,
    }


def _normalize_active_task(row: Any) -> dict[str, Any]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    provider = str(
        payload.get("provider")
        or payload.get("video_provider")
        or payload.get("image_provider")
        or payload.get("tool")
        or ""
    ).strip()
    return {
        "task_id": str(row.get("task_id") or ""),
        "task_type": str(row.get("task_type") or ""),
        "status": str(row.get("status") or ""),
        "progress": row.get("progress"),
        "stage_text": str(row.get("stage_text") or ""),
        "provider": provider,
        "shot_index": payload.get("shot_index"),
        "created_at": _json_safe_time(row.get("created_at")),
        "updated_at": _json_safe_time(row.get("updated_at")),
    }


def _json_safe_time(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


async def _ensure_no_active_export(db: AsyncSession, *, run_id: str, project_id: str, user_id: int) -> None:
    query = text(
        """
        SELECT task_id::text AS task_id, status
        FROM tasks
        WHERE (project_id = :project_id OR payload->>'project_id' = :project_id)
          AND user_id = :user_id
          AND task_type IN ('director_export_preview', 'director_export_final')
          AND status IN :active_statuses
          AND (run_id::text = :run_id OR payload->>'run_id' = :run_id)
        ORDER BY created_at DESC
        LIMIT 10
        """
    ).bindparams(bindparam("active_statuses", expanding=True))
    result = await db.execute(
        query,
        {"run_id": run_id, "project_id": project_id, "user_id": user_id, "active_statuses": ACTIVE_TASK_STATUSES},
    )
    rows = result.mappings().all()
    if rows:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Cannot export; an export task is already active for this run",
                "run_id": run_id,
                "project_id": project_id,
                "active_task_ids": [str(row["task_id"]) for row in rows],
                "active_task_statuses": [str(row["status"]) for row in rows],
            },
        )


@asynccontextmanager
async def _run_action_lock(db: AsyncSession, *, run_id: str, action: str):
    await _acquire_run_action_lock(db, run_id=run_id, action=action)
    try:
        yield
    finally:
        await _release_run_action_lock(db, run_id=run_id, action=action)


async def _acquire_run_action_lock(db: AsyncSession, *, run_id: str, action: str) -> None:
    result = await db.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtext(:lock_key), 0)"),
        {"lock_key": f"agent_run:{run_id}:{action}"},
    )
    if result.scalar_one() is not True:
        raise HTTPException(
            status_code=409,
            detail={"message": "Agent run action is already in progress", "action": action, "run_id": run_id},
        )


async def _release_run_action_lock(db: AsyncSession, *, run_id: str, action: str) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:lock_key), 0)"),
            {"lock_key": f"agent_run:{run_id}:{action}"},
        )
    except Exception:
        return


async def _audit_agent_run_action(
    *,
    user_id: int,
    action: str,
    run_id: str,
    project_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    await log_admin_action(
        user_id=user_id,
        action=action,
        target_type="agent_run",
        target_id=run_id,
        payload={"project_id": project_id, **(payload or {})},
    )

async def _reset_retryable_video_shots(db: AsyncSession, *, run_id: str, project_id: str, user_id: int) -> None:
    await db.execute(
        text(
            """
            UPDATE shot_rows s
            SET status = 'image_done', updated_at = NOW()
            WHERE s.project_id = :project_id
              AND s.user_id = :user_id
              AND s.selected_image IS NOT NULL
              AND s.selected_image <> ''
              AND (s.selected_video IS NULL OR s.selected_video = '')
              AND (
                s.last_error IS NOT NULL
                OR EXISTS (
                    SELECT 1 FROM tasks t
                    WHERE t.run_id = CAST(:run_id AS UUID)
                      AND t.project_id = :project_id
                      AND t.user_id = :user_id
                      AND t.task_type = 'video_gen'
                      AND t.status IN ('failed', 'dead_letter', 'cancelled')
                      AND (t.payload->>'shot_index')::int = s.shot_index
                )
              )
            """
        ),
        {"run_id": run_id, "project_id": project_id, "user_id": user_id},
    )
    await db.commit()


async def _selected_video_shot_indices(db: AsyncSession, *, project_id: str, user_id: int) -> list[int]:
    return [int(row["shot_index"]) for row in await _selected_video_rows(db, project_id=project_id, user_id=user_id)]


async def _selected_video_rows(db: AsyncSession, *, project_id: str, user_id: int) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT shot_index, selected_video
            FROM shot_rows
            WHERE project_id = :project_id
              AND user_id = :user_id
              AND selected_video IS NOT NULL
              AND selected_video <> ''
            ORDER BY shot_index ASC
            """
        ),
        {"project_id": project_id, "user_id": user_id},
    )
    return [dict(row) for row in result.mappings().all()]


def _signed_media_url_expired(url: str, *, now: datetime | None = None) -> bool:
    parsed = urlparse(str(url or ""))
    query = parse_qs(parsed.query)
    now = now or datetime.now(timezone.utc)

    expires_values = query.get("Expires") or query.get("expires")
    if expires_values:
        try:
            return datetime.fromtimestamp(int(expires_values[0]), timezone.utc) <= now
        except (TypeError, ValueError, OSError):
            pass

    tos_dates = query.get("X-Tos-Date") or query.get("x-tos-date")
    tos_expires = query.get("X-Tos-Expires") or query.get("x-tos-expires")
    if tos_dates and tos_expires:
        try:
            issued = datetime.strptime(tos_dates[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return issued + timedelta(seconds=int(tos_expires[0])) <= now
        except (TypeError, ValueError):
            return False
    return False


def _positive_int(value: Any, *, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} is required") from None
    if parsed <= 0:
        raise HTTPException(status_code=400, detail=f"{field} must be positive")
    return parsed


def _bounded_count(value: Any, *, default: int, max_count: int) -> int:
    if value in (None, ""):
        return default
    count = _positive_int(value, field="count")
    return min(count, max_count)


def _bounded_video_duration(value: Any, *, default: int) -> int:
    if value in (None, ""):
        return default
    duration = _positive_int(value, field="duration")
    if duration <= 5:
        return 5
    if duration <= 8:
        return 8
    if duration <= 10:
        return 10
    return 15


def _video_operation_for_duration(duration: int) -> str:
    if duration <= 5:
        return "video_gen_5s"
    if duration <= 8:
        return "video_gen_8s"
    if duration <= 10:
        return "video_gen_10s"
    return "video_gen_15s"


async def _load_shot_for_keyframe_pool(db: AsyncSession, *, project_id: str, user_id: int, shot_index: int) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT shot_index, prompt, duration, status, selected_image, selected_video,
                   image_candidates_json, video_variants_json, last_error
            FROM shot_rows
            WHERE project_id = :project_id AND user_id = :user_id AND shot_index = :shot_index
            LIMIT 1
            """
        ),
        {"project_id": project_id, "user_id": user_id, "shot_index": shot_index},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="shot not found")
    item = dict(row)
    item["image_candidates"] = item.pop("image_candidates_json", []) or []
    item["video_variants"] = item.pop("video_variants_json", []) or []
    return item


def _build_keyframe_variation_prompts(shot: dict[str, Any], *, count: int, strategy: str, instruction: str) -> list[dict[str, Any]]:
    base = str(shot.get("prompt") or "").strip()
    if not base:
        raise HTTPException(status_code=400, detail="shot prompt is required before keyframe batch generation")
    preflight = analyze_shot_risk(shot)
    if preflight.get("risk_level") == "blocked":
        codes = ", ".join(str(item.get("code") or "") for item in preflight.get("risks") or [] if isinstance(item, dict) and item.get("code"))
        raise HTTPException(
            status_code=400,
            detail={
                "message": "shot preflight blocked keyframe batch generation",
                "shot_index": shot.get("shot_index"),
                "risk_codes": codes,
                "director_preflight": preflight,
            },
        )
    labels_by_strategy = {
        "angle": ["侧脸关系角度", "道具/手部特写", "环境全景建立", "低机位情绪角度"],
        "lighting": ["冷色主光版本", "暖色侧逆光版本", "高对比电影光版本", "柔和自然光版本"],
        "action_step": ["动作起始帧", "动作推进帧", "情绪落点帧", "动作后反应帧"],
        "mixed": ["人物中近景", "关键道具特写", "环境氛围全景", "情绪反应特写"],
    }
    labels = labels_by_strategy.get(str(strategy or "").strip(), labels_by_strategy["mixed"])
    return [
        {
            "shot_index": shot.get("shot_index"),
            "variation": labels[index % len(labels)],
            "prompt": f"{base}，{labels[index % len(labels)]}，不得改变原分镜中的人物身份、地点、道具和动作目标。{instruction}".strip(),
        }
        for index in range(count)
    ]


async def _resolve_keyframe_candidate_url(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    shot: dict[str, Any],
    artifact_id: str,
    candidate_url: str,
) -> str:
    candidates = []
    selected_image = str(shot.get("selected_image") or "").strip()
    if selected_image:
        candidates.append(selected_image)
    raw_candidates = shot.get("image_candidates") if isinstance(shot.get("image_candidates"), list) else []
    for item in raw_candidates:
        if isinstance(item, dict):
            candidates.extend(str(item.get(key) or "").strip() for key in ("url", "uri", "image_url"))
        elif item:
            candidates.append(str(item).strip())
    if artifact_id:
        result = await db.execute(
            text(
                """
                SELECT uri
                FROM agent_artifacts
                WHERE id = CAST(:artifact_id AS UUID)
                  AND project_id = :project_id
                  AND user_id = :user_id
                  AND artifact_type IN ('image', 'keyframe', 'reference_image')
                LIMIT 1
                """
            ),
            {"artifact_id": artifact_id, "project_id": project_id, "user_id": user_id},
        )
        row = result.mappings().first()
        if row and str(row.get("uri") or "").strip():
            return str(row.get("uri") or "").strip()
    if candidate_url and candidate_url in {item for item in candidates if item}:
        return candidate_url
    if candidate_url and candidate_url.startswith(("/storage/", "/static/", "storage/", "uploads/", "http://", "https://")):
        return candidate_url
    raise HTTPException(status_code=400, detail="candidate image not found in keyframe pool")


async def _cancel_queued_run_tasks(db: AsyncSession, *, run_id: str, user_id: int) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT task_id::text AS task_id, credits_reserved, credit_transaction_id, payload
            FROM tasks
            WHERE run_id = CAST(:run_id AS UUID)
              AND user_id = :user_id
              AND status IN ('pending', 'queued')
            FOR UPDATE
            """
        ),
        {"run_id": run_id, "user_id": user_id},
    )
    rows = result.mappings().all()
    refunded = 0
    task_ids: list[str] = []
    for row in rows:
        task_ids.append(str(row["task_id"]))
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        transaction_id = str(row.get("credit_transaction_id") or payload.get("_credit_transaction_id") or "").strip()
        if transaction_id:
            refunded += await credit_service.refund(transaction_id)
    if task_ids:
        update_query = text(
            """
            UPDATE tasks
            SET status = 'cancelled', updated_at = NOW(), completed_at = NOW()
            WHERE task_id IN :task_ids
            """
        ).bindparams(bindparam("task_ids", expanding=True))
        await db.execute(
            update_query,
            {"task_ids": task_ids},
        )
    return {"cancelled_count": len(task_ids), "cancelled_task_ids": task_ids, "refunded_credits": refunded}
