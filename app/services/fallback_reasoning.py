"""Fallback Reasoning Module (兜底推理模块)

When the standard policy chain returns reject/ask/blocked and static recovery
maps offer no match, this module attempts a creative/contextual resolution:

  1. Checks the recovery pattern store for a known solution (fast path).
  2. If no pattern matches, calls DeepSeek with the full snapshot context.
  3. Returns a validated FallbackRecommendation that feeds back into the
     existing safety-gate → lane-check → dispatch pipeline.

Layer-3 in the three-tier processing chain:
  Layer-1: PolicySpec rule chain (13 stages, gates) — 95 % of cases.
  Layer-2: Static recovery map + Observer signals — 3 %.
  Layer-3: Fallback reasoning (this module) — 2 %, but determines
           overall robustness against novel situations.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.action_registry import REGISTRY as ACTION_REGISTRY
from app.services.credits import credit_service
from app.services.agent_runtime import publish_agent_event
from app.services.agent_runtime_contracts import (
    SafetyReviewRequired,
    ensure_safety_gate,
)
from app.services.agent_run_snapshot import get_agent_run_snapshot
from app.services.recovery_pattern_store import match_pattern, record_pattern

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FALLBACKS_PER_RUN = 3
"""Maximum number of fallback invocations per run (circuit breaker)."""

FALLBACK_COOLDOWN_SECONDS = 30
"""Minimum seconds between two fallback invocations on the same run."""

MIN_FALLBACK_CREDITS = 10
"""Minimum remaining run budget required to invoke the fallback LLM."""

FALLBACK_CONTEXT_CHAR_LIMIT = 64_000
"""Truncation budget for the snapshot context sent to the LLM."""

ALLOWED_FALLBACK_ACTIONS: set[str] = set(ACTION_REGISTRY.keys()) | {"escalate_human"}
"""Actions the fallback LLM is allowed to recommend."""

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FallbackTrigger:
    """Why the fallback was triggered."""

    source: str
    """One of: runtime_decision | observer_signal | gate_recovery_empty |
               unknown_action | decision_tick_blocked."""

    kind: str
    """One of: reject | ask | blocked | recover | empty_recovery."""

    parent_decision: dict[str, Any]
    """The decision / result that triggered this fallback."""

    context_snapshot: dict[str, Any] | None = None
    """Full agent-run snapshot at trigger time (may be None on some paths)."""

    reason: str = ""
    """Human-readable reason from the triggering decision."""

    stage_id: str = ""
    """Production stage that was blocked, when applicable."""


@dataclass(frozen=True)
class FallbackRecommendation:
    """Structured output returned by the fallback LLM after validation."""

    action: str
    """Recommended action — must be one of ALLOWED_FALLBACK_ACTIONS."""

    params: dict[str, Any]
    """Action-specific parameters (e.g. target_shots, style hints)."""

    user_message: str
    """Chinese message shown to the user explaining the situation."""

    reasoning: str
    """LLM's internal chain-of-thought (stored as thinking_artifact)."""

    confidence: float
    """0.0 — 1.0 confidence in this recommendation."""

    requires_human_confirmation: bool
    """True → gate the recommendation behind a user confirmation step."""

    dispatch_ready: bool
    """True → can proceed directly to the dispatch pipeline after validation."""

    fallback_kind: str
    """One of resolved | partial | escalate."""

    evidence_refs: list[dict[str, Any]]
    """References to the evidence that informed this recommendation."""

    extracted_insight: dict[str, Any]
    """Pattern summary for the recovery pattern store (learning)."""


@dataclass(frozen=True)
class FallbackResult:
    """Final result after running fallback reasoning."""

    triggered: bool
    """True if fallback actually fired (eligible + processed)."""

    recommendation: FallbackRecommendation | None = None
    """The validated recommendation, if produced."""

    used_recovery_pattern: bool = False
    """True when a stored pattern was matched instead of calling the LLM."""

    pattern_match_id: str = ""
    """ID of the matched recovery pattern, if applicable."""

    thinking_artifact_id: str = ""
    """ID of the stored thinking artifact (LLM response ID), if applicable."""

    events_written: list[str] = field(default_factory=list)
    """IDs of audit events published by this fallback attempt."""

    budget_spent: float = 0.0
    """Credits consumed by the LLM call (if any)."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def attempt_fallback(
    db: AsyncSession,
    *,
    run_id: str,
    project_id: str,
    user_id: int,
    instruction: str,
    trigger: FallbackTrigger,
    fallback_count: int = 0,
    previous_fallbacks: list[dict[str, Any]] | None = None,
) -> FallbackResult:
    """Main entry-point: attempt to reason about a blocked / rejected situation.

    The function is guarded by a circuit breaker (``fallback_count``) so that
    repeated failures on the same run do not keep consuming credits.

    Returns a ``FallbackResult`` containing either a validated recommendation
    or an escalation signal.
    """
    # 1 — Circuit breaker: hard cap per run
    if fallback_count >= MAX_FALLBACKS_PER_RUN:
        logger.info("Fallback circuit breaker tripped for run %s (%d/%d)", run_id, fallback_count, MAX_FALLBACKS_PER_RUN)
        return _circuit_breaker_result(trigger)

    # 2 — Fetch snapshot (required for context)
    snapshot = await get_agent_run_snapshot(db, run_id=run_id, user_id=user_id)
    if not snapshot:
        logger.warning("Fallback: cannot build snapshot for run %s", run_id)
        return _no_snapshot_result(trigger)

    # 3 — Check recovery pattern store (fast path, avoids LLM call)
    pattern = await _match_pattern(db, trigger, snapshot)
    if pattern is not None:
        recommendation = _instantiate_from_pattern(pattern, trigger, instruction)
        result = FallbackResult(
            triggered=True,
            recommendation=recommendation,
            used_recovery_pattern=True,
            pattern_match_id=pattern.get("pattern_id", ""),
        )
    else:
        # 4 — Call DeepSeek with compressed snapshot context
        recommendation, thinking_id = await _call_fallback_llm(
            snapshot=snapshot,
            instruction=instruction,
            trigger=trigger,
            previous_fallbacks=previous_fallbacks,
            user_id=user_id,
        )
        result = FallbackResult(
            triggered=True,
            recommendation=recommendation,
            used_recovery_pattern=False,
            thinking_artifact_id=thinking_id or "",
        )

    # 5 — Validate & sanitise
    if result.recommendation:
        result = _validate_and_sanitize(result)

    # 6 — Write audit trail
    events = await _write_fallback_events(db, run_id, project_id, user_id, trigger, result)
    result = FallbackResult(
        triggered=result.triggered,
        recommendation=result.recommendation,
        used_recovery_pattern=result.used_recovery_pattern,
        pattern_match_id=result.pattern_match_id,
        thinking_artifact_id=result.thinking_artifact_id,
        events_written=events,
        budget_spent=result.budget_spent,
    )

    # 7 — If resolved, record the pattern for future learning
    if (
        result.recommendation
        and result.recommendation.fallback_kind == "resolved"
        and result.recommendation.confidence >= 0.8
        and not result.used_recovery_pattern
        and result.recommendation.extracted_insight
    ):
        await _record_pattern(db, trigger, result.recommendation)

    return result


# ---------------------------------------------------------------------------
# Eligibility (used by callers before calling attempt_fallback)
# ---------------------------------------------------------------------------

def is_eligible_for_fallback(
    decision_kind: str,
    decision_reason: str,
    *,
    has_production_state: bool = False,
    remaining_budget: int | float = 0,
    fallback_count: int = 0,
) -> tuple[bool, str]:
    """Determine whether a rejected / asked decision should trigger fallback.

    Returns ``(eligible, reason)``.
    """
    # Only fire for reject / ask / blocked
    if decision_kind not in {"reject", "ask", "blocked"}:
        return False, "wrong_decision_kind"

    # Cancelled runs: trivial, skip
    if decision_reason == "run_cancelled":
        return False, "run_cancelled"

    # Busy gate: transient, skip
    if decision_reason == "busy_gate":
        return False, "busy_gate"

    # Trivial unregistered action without production context
    if decision_reason == "capability_not_registered" and not has_production_state:
        return False, "trivial_unregistered_action"

    # Circuit breaker
    if fallback_count >= MAX_FALLBACKS_PER_RUN:
        return False, "circuit_breaker_exceeded"

    # Budget gate
    if int(remaining_budget or 0) < MIN_FALLBACK_CREDITS:
        return False, "insufficient_budget"

    return True, "eligible"


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

async def _call_fallback_llm(
    *,
    snapshot: dict[str, Any],
    instruction: str,
    trigger: FallbackTrigger,
    previous_fallbacks: list[dict[str, Any]] | None,
    user_id: int | None = None,
) -> tuple[FallbackRecommendation | None, str]:
    """Call DeepSeek with a compressed fallback context.

    Returns ``(recommendation, thinking_artifact_id)``.
    ``thinking_artifact_id`` is the response ``id`` from the API, or ``""``.
    """
    settings = get_settings()
    if not settings.deepseek_api_key:
        logger.warning("Fallback LLM: no DeepSeek API key configured")
        return None, ""

    context = _build_fallback_context(snapshot, instruction, trigger)
    request_body = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": _FALLBACK_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
        "stream": False,
        "response_format": {"type": "json_object"},
    }

    timeout = httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(
                f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Fallback LLM HTTP error: %s", exc)
            return None, ""
        except httpx.TimeoutException:
            logger.error("Fallback LLM timeout")
            return None, ""
        except Exception as exc:
            logger.error("Fallback LLM unexpected error: %s", exc)
            return None, ""

    data = response.json()
    # Charge LLM token usage (non-blocking)
    if user_id is not None:
        usage = data.get("usage") or {}
        token_count = usage.get("total_tokens", 0)
        if token_count > 0:
            try:
                await credit_service.charge_direct(
                    user_id=user_id,
                    operation="llm_planner_call",
                    token_count=token_count,
                    ref_id=f"llm:fallback:{instruction.strip()[:40]}",
                )
            except Exception:
                logger.warning("Failed to charge LLM tokens (non-blocking)", exc_info=True)
    raw = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    parsed = _extract_json_object(raw)
    recommendation = _parse_recommendation(parsed)
    thinking_id = str(data.get("id", ""))
    return recommendation, thinking_id


def _build_fallback_context(
    snapshot: dict[str, Any],
    instruction: str,
    trigger: FallbackTrigger,
    previous_fallbacks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compile a concise fallback context from the full snapshot.

    Only the most relevant sections are included to stay within the LLM
    context budget.
    """
    run = snapshot.get("run", {})
    state_machine = snapshot.get("state_machine", {})
    decision_context = snapshot.get("decision_context", {})
    flow = snapshot.get("flow", [])
    evidence = snapshot.get("evidence", {})
    budget = snapshot.get("budget", {})
    outputs = snapshot.get("outputs", {})
    shots = outputs.get("shots") if isinstance(outputs, dict) else []

    if isinstance(shots, list):
        shot_count = len(shots)
        selected_image_count = sum(1 for s in shots if s.get("selected_image"))
        selected_video_count = sum(1 for s in shots if s.get("selected_video"))
        final_video_url = bool(any(s.get("final_video_url") for s in shots if isinstance(s, dict)))
    else:
        shot_count = evidence.get("shot_count", 0)
        selected_image_count = evidence.get("selected_image_count", 0)
        selected_video_count = evidence.get("selected_video_count", 0)
        final_video_url = bool(evidence.get("final_video_url"))

    stages = []
    for stage in (flow or []):
        if isinstance(stage, dict):
            stages.append({
                "id": stage.get("id"),
                "action": stage.get("action"),
                "status": stage.get("status"),
                "progress": stage.get("progress", 0),
                "gate_allowed": stage.get("gate", {}).get("allowed") if isinstance(stage.get("gate"), dict) else None,
                "gate_missing": stage.get("gate", {}).get("missing", []) if isinstance(stage.get("gate"), dict) else [],
                "gate_reason": stage.get("gate", {}).get("reason", "") if isinstance(stage.get("gate"), dict) else "",
            })

    return {
        "task": "fallback_reasoning",
        "run_goal": run.get("goal", ""),
        "run_status": run.get("status", ""),
        "current_phase": run.get("current_phase", ""),
        "user_instruction": instruction,
        "trigger_source": trigger.source,
        "trigger_kind": trigger.kind,
        "trigger_reason": trigger.reason,
        "blocked_by": state_machine.get("missing", []),
        "block_reason": state_machine.get("reason", ""),
        "production_stages": stages,
        "shot_context": {
            "shot_count": shot_count,
            "selected_image_count": selected_image_count,
            "selected_video_count": selected_video_count,
            "has_final_video": final_video_url,
        },
        "active_tasks": sum(1 for s in stages if s.get("status") == "running"),
        "budget_remaining": budget.get("remaining_run_budget", 0),
        "previous_fallbacks": (previous_fallbacks or [])[-3:],
        "allowed_actions": sorted(ALLOWED_FALLBACK_ACTIONS),
    }


_FALLBACK_SYSTEM_PROMPT = """
You are the Fallback Reasoning Engine for an AI short-drama production system. Your role is to diagnose situations where the standard policy chain cannot proceed.

## CONTEXT
You will receive:
1. Current production state (stages, gates, progress)
2. The reason the standard chain failed
3. The user's original instruction
4. Shot/media state

## YOUR TASK
Analyse why the system is stuck and recommend a recovery path. Be creative but safe — you can only RECOMMEND actions, not execute them.

## CONSTRAINTS
- Your recommended action MUST be one of the allowed_actions list.
- If you are unsure, set fallback_kind to "partial" and ask the user one clarifying question.
- If you cannot find any reasonable path, set fallback_kind to "escalate".
- If you have high confidence in a resolution, set fallback_kind to "resolved" and dispatch_ready=true.
- Never recommend dangerous actions or actions not in the allowed list.
- Never suggest overriding budget or safety gates.

## OUTPUT FORMAT
Return JSON only with these keys:
- action: one of allowed_actions or "escalate_human"
- params: object with action-specific parameters (empty object if none)
- user_message: concise Chinese message to the user explaining the situation and next step
- reasoning: your internal chain-of-thought in Chinese (stored as thinking artifact)
- confidence: 0.0-1.0
- requires_human_confirmation: true if user must approve before execution
- dispatch_ready: true if action can proceed immediately after validation
- fallback_kind: "resolved" | "partial" | "escalate"
- extracted_insight: object summarising the pattern for future learning
""".strip()


# ---------------------------------------------------------------------------
# Recommendation parsing
# ---------------------------------------------------------------------------

def _parse_recommendation(parsed: dict[str, Any]) -> FallbackRecommendation | None:
    """Parse and validate the LLM's raw JSON output into a recommendation."""
    action = str(parsed.get("action") or "").strip()
    if not action:
        logger.warning("Fallback LLM returned empty action")
        return None

    if action not in ALLOWED_FALLBACK_ACTIONS and action not in ("escalate_human",):
        logger.warning("Fallback LLM returned unknown action: %s", action)
        return None

    params = parsed.get("params")
    if not isinstance(params, dict):
        params = {}

    fallback_kind = str(parsed.get("fallback_kind") or "escalate").strip().lower()
    if fallback_kind not in {"resolved", "partial", "escalate"}:
        fallback_kind = "escalate"

    evidence_refs = parsed.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        evidence_refs = []
    evidence_refs = [ref for ref in evidence_refs if isinstance(ref, dict)]

    extracted_insight = parsed.get("extracted_insight")
    if not isinstance(extracted_insight, dict):
        extracted_insight = {}

    return FallbackRecommendation(
        action=action,
        params=params,
        user_message=str(parsed.get("user_message") or ""),
        reasoning=str(parsed.get("reasoning") or ""),
        confidence=_clamp_confidence(parsed.get("confidence")),
        requires_human_confirmation=bool(parsed.get("requires_human_confirmation", True)),
        dispatch_ready=bool(parsed.get("dispatch_ready", False)) and fallback_kind == "resolved",
        fallback_kind=fallback_kind,
        evidence_refs=evidence_refs,
        extracted_insight=extracted_insight,
    )


def _clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Fault-tolerant JSON extraction, same pattern as llm_planner."""
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        logger.warning("Fallback LLM returned non-JSON content: %.200s", raw)
        return {}
    candidate = text[start: end + 1]
    try:
        result = json.loads(candidate)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Fallback LLM returned unparseable content: %.200s", raw)
        return {}


# ---------------------------------------------------------------------------
# Validation & sanitisation
# ---------------------------------------------------------------------------

def _validate_and_sanitize(result: FallbackResult) -> FallbackResult:
    """Validate the recommendation against safety rules and the capability registry.

    Returns a sanitised ``FallbackResult`` — may downgrade ``fallback_kind``
    to ``"escalate"`` if validation fails.
    """
    rec = result.recommendation
    if rec is None:
        return result

    # --- Action must be in the allowed list ---
    if rec.action not in ALLOWED_FALLBACK_ACTIONS and rec.action != "escalate_human":
        return _escalate_result(result, f"Recommended action '{rec.action}' not in allowed actions list")

    # --- Safety gate ---
    try:
        ensure_safety_gate({
            "action": rec.action,
            "risk": {"score": 0.0},
        })
    except SafetyReviewRequired as exc:
        return _escalate_result(result, f"Safety gate rejected recommended action '{rec.action}': {exc}")

    # --- Clamp confidence ---
    sanitised_rec = FallbackRecommendation(
        action=rec.action,
        params=rec.params,
        user_message=rec.user_message,
        reasoning=rec.reasoning,
        confidence=max(0.0, min(1.0, rec.confidence)),
        requires_human_confirmation=rec.requires_human_confirmation,
        dispatch_ready=rec.dispatch_ready and rec.fallback_kind == "resolved",
        fallback_kind=rec.fallback_kind if rec.fallback_kind in {"resolved", "partial", "escalate"} else "escalate",
        evidence_refs=rec.evidence_refs,
        extracted_insight=rec.extracted_insight,
    )
    return FallbackResult(
        triggered=result.triggered,
        recommendation=sanitised_rec,
        used_recovery_pattern=result.used_recovery_pattern,
        pattern_match_id=result.pattern_match_id,
        thinking_artifact_id=result.thinking_artifact_id,
        events_written=result.events_written,
        budget_spent=result.budget_spent,
    )


def _escalate_result(original: FallbackResult, reason: str) -> FallbackResult:
    """Build an escalated FallbackResult from a failed validation."""
    return FallbackResult(
        triggered=original.triggered,
        recommendation=FallbackRecommendation(
            action="escalate_human",
            params={},
            user_message="系统兜底推理模块推荐了不允许的操作，需要人工介入。",
            reasoning=reason,
            confidence=0.0,
            requires_human_confirmation=True,
            dispatch_ready=False,
            fallback_kind="escalate",
            evidence_refs=[],
            extracted_insight={},
        ),
        used_recovery_pattern=original.used_recovery_pattern,
        pattern_match_id=original.pattern_match_id,
        thinking_artifact_id=original.thinking_artifact_id,
        events_written=original.events_written,
        budget_spent=original.budget_spent,
    )


# ---------------------------------------------------------------------------
# Circuit breaker / empty-snapshot results
# ---------------------------------------------------------------------------

def _circuit_breaker_result(trigger: FallbackTrigger) -> FallbackResult:
    return FallbackResult(
        triggered=False,
        recommendation=FallbackRecommendation(
            action="escalate_human",
            params={},
            user_message="当前情况自动推理次数已达上限，需要人工介入处理。",
            reasoning=f"Circuit breaker: {MAX_FALLBACKS_PER_RUN} fallbacks exhausted for this run",
            confidence=0.0,
            requires_human_confirmation=True,
            dispatch_ready=False,
            fallback_kind="escalate",
            evidence_refs=[],
            extracted_insight={},
        ),
    )


def _no_snapshot_result(trigger: FallbackTrigger) -> FallbackResult:
    return FallbackResult(
        triggered=False,
        recommendation=FallbackRecommendation(
            action="escalate_human",
            params={},
            user_message="无法获取当前项目快照，需要人工介入处理。",
            reasoning="Snapshot is None — cannot build fallback context",
            confidence=0.0,
            requires_human_confirmation=True,
            dispatch_ready=False,
            fallback_kind="escalate",
            evidence_refs=[],
            extracted_insight={},
        ),
    )


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------

async def _write_fallback_events(
    db: AsyncSession,
    run_id: str,
    project_id: str,
    user_id: int,
    trigger: FallbackTrigger,
    result: FallbackResult,
) -> list[str]:
    """Write fallback audit trail as agent_events.

    Returns a list of written event IDs.
    """
    rec = result.recommendation
    fallback_kind = rec.fallback_kind if rec else "escalate"
    action = rec.action if rec else "escalate_human"

    event = await publish_agent_event(
        db,
        run_id=run_id,
        project_id=project_id,
        user_id=user_id,
        source="fallback_reasoning",
        event_type="decision",
        phase=f"fallback_{fallback_kind}",
        title="兜底推理模块处理",
        detail=f"Trigger: {trigger.source}/{trigger.kind} -> {fallback_kind} action={action}",
        status="done",
        progress=85 if rec and rec.dispatch_ready else 75,
        meta={
            "fallback_trigger": {
                "source": trigger.source,
                "kind": trigger.kind,
                "reason": trigger.reason,
                "stage_id": trigger.stage_id,
            },
            "fallback_result": {
                "action": action,
                "fallback_kind": fallback_kind,
                "confidence": rec.confidence if rec else 0.0,
                "used_recovery_pattern": result.used_recovery_pattern,
                "dispatch_ready": rec.dispatch_ready if rec else False,
                "requires_human_confirmation": rec.requires_human_confirmation if rec else True,
            },
            "used_recovery_pattern": result.used_recovery_pattern,
            "pattern_match_id": result.pattern_match_id,
            "thinking_artifact_id": result.thinking_artifact_id,
        },
        actor="fallback_reasoning",
        event_kind="recovery",
        visibility="expert",
        summary=f"Fallback: {trigger.reason} -> {fallback_kind}({action})",
        reason=trigger.reason,
    )
    event_id = str(event.get("id", "")) if event else ""
    return [event_id] if event_id else []


# ---------------------------------------------------------------------------
# Recovery pattern store (lightweight inline; production version
# should use recovery_pattern_store.py)
# ---------------------------------------------------------------------------

async def _match_pattern(
    db: AsyncSession,
    trigger: FallbackTrigger,
    snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    """Check the recovery pattern store for a known solution."""
    sm = snapshot.get("state_machine", {})
    missing = [str(m) for m in (sm.get("missing", []) or [])]
    return await match_pattern(
        db,
        trigger_source=trigger.source,
        trigger_kind=trigger.kind,
        trigger_reason=trigger.reason,
        missing_items=missing,
    )


async def _record_pattern(
    db: AsyncSession,
    trigger: FallbackTrigger,
    recommendation: FallbackRecommendation,
) -> None:
    """Store a successful fallback pattern for future reuse."""
    sm = trigger.context_snapshot.get("state_machine", {}) if trigger.context_snapshot else {}
    missing = [str(m) for m in (sm.get("missing", []) or [])]
    await record_pattern(
        db,
        trigger_source=trigger.source,
        trigger_kind=trigger.kind,
        trigger_reason=trigger.reason,
        missing_items=missing,
        recommendation_action=recommendation.action,
        confidence=recommendation.confidence,
        metadata=recommendation.extracted_insight,
    )


def _instantiate_from_pattern(
    pattern: dict[str, Any],
    trigger: FallbackTrigger,  # noqa: ARG001
    instruction: str,
) -> FallbackRecommendation:
    """Create a recommendation from a stored pattern (avoids LLM call)."""
    metadata = pattern.get("metadata") or {}
    return FallbackRecommendation(
        action=pattern.get("recommendation_action", "escalate_human"),
        params=metadata.get("params", {}),
        user_message=metadata.get("user_message", "根据之前相似情况的处理经验，建议尝试标准恢复流程。"),
        reasoning=metadata.get("reasoning", ""),
        confidence=float(pattern.get("confidence", 0.7)),
        requires_human_confirmation=bool(metadata.get("requires_human_confirmation", True)),
        dispatch_ready=bool(metadata.get("dispatch_ready", False)),
        fallback_kind="resolved",
        evidence_refs=metadata.get("evidence_refs", []),
        extracted_insight=metadata,
    )
