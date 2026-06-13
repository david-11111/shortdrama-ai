from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import decision_mailbox, main_chain_feedback
from app.services.agent_runtime import publish_agent_event, update_agent_run
from app.services.agent_runtime_contracts import RuntimeFeedback, SafetyReviewRequired, ensure_safety_gate
from app.services.run_coordination import DecisionTickResult
from app.services.run_dispatch_gateway import DispatchGatewayContext, dispatch_authoritative_packet

GatewayHandler = Callable[[], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class MainChainContext:
    project_id: str
    user_id: int
    user_tier: str
    run_id: str
    run_mode: str


@dataclass(frozen=True)
class MainChainResult:
    status: str
    dispatched: bool
    decision: dict[str, Any]
    result: dict[str, Any] | None = None


async def apply_decision_packet(
    db: AsyncSession,
    *,
    packet: DecisionTickResult,
    context: MainChainContext,
    handlers: dict[str, GatewayHandler],
) -> MainChainResult:
    try:
        ensure_safety_gate(packet.as_dict())
    except SafetyReviewRequired as exc:
        await _publish_safety_block(db, packet=packet, context=context, reason=str(exc))
        return MainChainResult("blocked", False, packet.as_dict(), {"safety_block": str(exc)})

    if packet.status == "execute" and packet.dispatchable and packet.allowed:
        await decision_mailbox.submit_decision(
            db,
            run_id=context.run_id,
            project_id=context.project_id,
            user_id=context.user_id,
            packet=packet.as_dict(),
            decision_rationale=packet.reason,
            thinking_artifacts=[
                {
                    "type": "decision_evidence",
                    "evidence_refs": packet.evidence_refs,
                    "candidate_actions": packet.candidate_actions,
                    "budget": packet.budget,
                    "risk": packet.risk,
                },
                {
                    "type": "planner_audit",
                    "root_cause_layer": packet.root_cause_layer,
                    "decision_rationale": packet.decision_rationale,
                },
            ],
        )
        result = await dispatch_authoritative_packet(
            db,
            packet=packet,
            context=DispatchGatewayContext(
                project_id=context.project_id,
                user_id=context.user_id,
                user_tier=context.user_tier,
                run_id=context.run_id,
                run_mode=context.run_mode,
                runtime_features=_runtime_features_for_action(packet.action),
                provider_capabilities=_provider_capabilities_for_action(packet.action),
                capability_versions=_capability_versions_for_action(packet.action),
            ),
            handlers=handlers,
        )
        return MainChainResult("dispatched", True, packet.as_dict(), result)

    if packet.status == "wait":
        await _publish_state(db, packet=packet, context=context, status="running", phase=packet.action or "wait")
        return MainChainResult("waiting", False, packet.as_dict())

    if packet.status == "complete":
        await _publish_state(
            db,
            packet=packet,
            context=context,
            status="completed",
            phase=packet.stage_id or "writeback_review",
        )
        return MainChainResult("completed", False, packet.as_dict())

    if packet.status == "recover":
        phase = "fallback_reasoning" if packet.fallback_action == "fallback_reasoning" else "recover"
        await _publish_state(db, packet=packet, context=context, status="blocked", phase=phase)
        return MainChainResult("recover", False, packet.as_dict())

    await _publish_state(db, packet=packet, context=context, status="blocked", phase=packet.stage_id or "blocked")
    return MainChainResult("blocked", False, packet.as_dict())


async def _publish_safety_block(
    db: AsyncSession,
    *,
    packet: DecisionTickResult,
    context: MainChainContext,
    reason: str,
) -> None:
    await _publish_state(db, packet=packet, context=context, status="blocked", phase="safety_review")
    await _maybe_await(
        main_chain_feedback.publish_runtime_feedback(
            db,
            run_id=context.run_id,
            project_id=context.project_id,
            user_id=context.user_id,
            feedback=RuntimeFeedback(
                status="blocked",
                summary=f"Safety block: {packet.action}",
                next_step="Manual review is required before this action can run.",
                evidence=packet.evidence_refs,
                risk=packet.risk,
                requires_user=True,
                call_to_action={
                    "type": "dangerous_action_review",
                    "action": packet.action,
                    "approvers": ["admin", "product_owner"],
                    "timeout_minutes": 60,
                    "reason": reason,
                },
            ),
        )
    )


async def _publish_state(
    db: AsyncSession,
    *,
    packet: DecisionTickResult,
    context: MainChainContext,
    status: str,
    phase: str,
) -> None:
    await _maybe_await(
        update_agent_run(
            db,
            run_id=context.run_id,
            status=status,
            current_phase=phase,
            summary=packet.reason,
            final_decision=packet.action,
        )
    )
    await _maybe_await(
        publish_agent_event(
            db,
            run_id=context.run_id,
            project_id=context.project_id,
            user_id=context.user_id,
            source="main_chain",
            event_type="decision",
            phase=phase,
            title="Main chain decision",
            detail=f"{packet.status}: {packet.action}",
            status=status,
            progress=None,
            meta={"decision_packet": packet.as_dict()},
            event_kind="decision",
            visibility="debug",
            summary=f"{packet.status}: {packet.action}",
            reason=packet.reason,
        )
    )
    await _maybe_await(
        main_chain_feedback.publish_runtime_feedback(
            db,
            run_id=context.run_id,
            project_id=context.project_id,
            user_id=context.user_id,
            feedback=RuntimeFeedback(
                status=_feedback_status(status, packet.status),
                summary=f"{packet.status}: {packet.action}",
                next_step=packet.reason,
                evidence=packet.evidence_refs,
                risk=packet.risk,
                requires_user=packet.status in {"blocked", "recover", "ask_human"},
            ),
        )
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _feedback_status(run_status: str, packet_status: str) -> str:
    if packet_status == "wait":
        return "waiting"
    if packet_status == "recover":
        return "recovering"
    if packet_status == "complete":
        return "completed"
    if run_status == "blocked":
        return "blocked"
    return run_status


def _runtime_features_for_action(action: str) -> list[str]:
    from app.services.action_registry import features_for_action
    return features_for_action(action)


def _provider_capabilities_for_action(action: str) -> list[str]:
    from app.services.action_registry import providers_for_action
    return providers_for_action(action)


def _capability_versions_for_action(action: str) -> dict[str, str]:
    from app.services.action_registry import lookup
    r = lookup(action)
    if r and r.requires_features:
        return {action: "2026-05-27.v1"}
    return {}
