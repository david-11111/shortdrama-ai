from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services.action_registry import registered_planner_actions
from app.services.credits import credit_service
from app.services.run_coordination import UnifiedRunFacts

logger = logging.getLogger(__name__)


async def llm_suggest_tick(facts: UnifiedRunFacts) -> dict[str, Any] | None:
    """Call DeepSeek with run context to suggest the next coordination action.

    Returns a dict with optional keys: action, decision_rationale, root_cause_layer,
    evidence_refs, confidence. Returns None if unavailable or the call fails.
    """
    settings = get_settings()
    if not getattr(settings, "llm_coordination_enabled", False):
        return None
    if not settings.deepseek_api_key:
        return None

    try:
        return await _call_deepseek_tick(facts, settings)
    except Exception as exc:
        logger.warning("LLM coordination tick failed, using deterministic path: %s", exc)
        return None


async def _call_deepseek_tick(facts: UnifiedRunFacts, settings: Any) -> dict[str, Any] | None:
    allowed = sorted(registered_planner_actions())
    context = _build_tick_context(facts)

    system_prompt = (
        "You are the root-cause analysis layer for an AI short-drama production coordinator. "
        "Given the current run state (shots, tasks, production stage, evidence), suggest the next action. "
        f"Allowed actions: {', '.join(allowed)}. "
        "Analyze: what is the production bottleneck? Which layer is stuck? "
        "Output a JSON object with: action (one of the allowed values), decision_rationale (concise Chinese "
        "diagnostic sentence), root_cause_layer (shot|asset|provider|script|workflow|none), "
        "evidence_refs (list of {kind,key} objects), confidence (0.0-1.0). "
        "If nothing is actionable, action should be an empty string and confidence 0.0. "
        "Return JSON only."
    )

    request_body = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
        "stream": False,
        "response_format": {"type": "json_object"},
    }

    timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        response.raise_for_status()

    data = response.json()
    # Charge LLM token usage (non-blocking)
    user_id = getattr(facts, "user_id", None)
    if user_id is not None:
        usage = data.get("usage") or {}
        token_count = usage.get("total_tokens", 0)
        if token_count > 0:
            try:
                await credit_service.charge_direct(
                    user_id=user_id,
                    operation="llm_planner_call",
                    token_count=token_count,
                    ref_id=f"llm:tick:{str(facts.run.get('run_id', ''))[:20]}",
                )
            except Exception:
                logger.warning("Failed to charge LLM tokens (non-blocking)", exc_info=True)
    raw = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None

    suggested_action = str(parsed.get("action") or "").strip()
    if suggested_action and suggested_action not in allowed:
        suggested_action = ""

    confidence = 0.0
    try:
        confidence = float(parsed.get("confidence", 0))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        pass

    evidence_refs = parsed.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        evidence_refs = []

    return {
        "action": suggested_action,
        "decision_rationale": str(parsed.get("decision_rationale") or "").strip(),
        "root_cause_layer": str(parsed.get("root_cause_layer") or "").strip(),
        "evidence_refs": [ref for ref in evidence_refs if isinstance(ref, dict)],
        "confidence": confidence,
    }


def _build_tick_context(facts: UnifiedRunFacts) -> dict[str, Any]:
    production = facts.production_run
    shots_summary = []
    for shot in facts.shots[:20]:
        shots_summary.append({
            "shot_index": shot.get("shot_index"),
            "status": shot.get("status"),
            "has_image": bool(shot.get("selected_image")),
            "has_video": bool(shot.get("selected_video")),
            "last_error": str(shot.get("last_error") or "")[:120],
        })

    tasks_summary = []
    for task in facts.tasks[:20]:
        tasks_summary.append({
            "task_type": task.get("task_type"),
            "status": task.get("status"),
            "error_message": str(task.get("error_message") or "")[:120],
            "retry_count": task.get("retry_count", 0),
        })

    return {
        "run_status": production.get("status"),
        "current_stage": production.get("current_stage"),
        "goal": str(facts.run.get("goal") or ""),
        "shot_count": len(facts.shots),
        "shots_with_image": sum(1 for s in facts.shots if s.get("selected_image")),
        "shots_with_video": sum(1 for s in facts.shots if s.get("selected_video")),
        "active_task_count": sum(1 for t in facts.tasks if str(t.get("status") or "") in {"queued", "running"}),
        "failed_task_count": sum(1 for t in facts.tasks if str(t.get("status") or "") in {"failed", "dead_letter"}),
        "shots": shots_summary,
        "tasks": tasks_summary,
        "planner_audit": facts.planner_audit,
    }


def merge_llm_suggestion(
    decision_dict: dict[str, Any],
    llm_suggestion: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge LLM coordination suggestion into a deterministic decision dict.

    Rules (conservative):
    - LLM decision_rationale and root_cause_layer always override defaults (non-destructive enrichment)
    - LLM evidence_refs are appended (deduplicated by kind+key)
    - LLM action overrides only when state_machine status is NOT "execute"
    - Never changes lane or dispatchable status
    """
    if not llm_suggestion:
        return decision_dict

    merged = dict(decision_dict)

    # Always enrich with LLM audit data
    if llm_suggestion.get("decision_rationale"):
        merged["decision_rationale"] = llm_suggestion["decision_rationale"]
    if llm_suggestion.get("root_cause_layer"):
        merged["root_cause_layer"] = llm_suggestion["root_cause_layer"]

    # Merge evidence_refs
    existing_refs = list(merged.get("evidence_refs") or [])
    for ref in llm_suggestion.get("evidence_refs") or []:
        if isinstance(ref, dict) and ref not in existing_refs:
            existing_refs.append(ref)
    merged["evidence_refs"] = existing_refs

    # Action override: only when state machine isn't confidently executing
    sm_status = str(merged.get("status") or "")
    llm_action = str(llm_suggestion.get("action") or "").strip()
    if llm_action and sm_status not in {"execute", "complete"}:
        sm_action = str(merged.get("action") or "")
        if llm_action != sm_action:
            merged["action"] = llm_action
            merged["reason"] = (
                f"{merged.get('reason', '')} | LLM override: {llm_suggestion.get('decision_rationale', '')}"
            ).strip(" |")

    return merged
