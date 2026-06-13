from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import decision_mailbox, main_chain_feedback
from app.services.agent_runtime import publish_agent_event, update_agent_run
from app.services.agent_runtime_contracts import (
    CapabilityViolation,
    RuntimeFeedback,
    ensure_lane_can,
    ensure_runtime_requirements,
)
from app.services.run_coordination import DecisionTickResult

DispatchHandler = Callable[[], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class DispatchGatewayContext:
    project_id: str
    user_id: int
    user_tier: str
    run_id: str
    run_mode: str
    runtime_features: list[str] = field(default_factory=list)
    provider_capabilities: list[str] = field(default_factory=list)
    capability_versions: dict[str, str] = field(default_factory=dict)


async def dispatch_authoritative_packet(
    db: AsyncSession,
    *,
    packet: DecisionTickResult,
    context: DispatchGatewayContext,
    handlers: dict[str, DispatchHandler],
) -> dict[str, Any]:
    mission = _validate_packet(packet)
    action = str(mission["action"])
    lane = str(mission["lane"])
    decision_id = str(mission.get("mission_id") or f"{context.run_id}:{action}")
    try:
        ensure_lane_can(lane, _capability_for_action(action))
    except CapabilityViolation as exc:
        await decision_mailbox.mark_decision_rejected(
            db,
            run_id=context.run_id,
            project_id=context.project_id,
            user_id=context.user_id,
            decision_id=decision_id,
            reason=str(exc),
        )
        raise ValueError(str(exc)) from exc

    try:
        ensure_runtime_requirements(
            action,
            {
                "runtime_features": context.runtime_features,
                "provider_capabilities": context.provider_capabilities,
                "capability_versions": context.capability_versions,
            },
        )
    except CapabilityViolation as exc:
        await decision_mailbox.mark_decision_rejected(
            db,
            run_id=context.run_id,
            project_id=context.project_id,
            user_id=context.user_id,
            decision_id=decision_id,
            reason=str(exc),
        )
        raise ValueError(str(exc)) from exc

    handler = handlers.get(action)
    if handler is None:
        raise ValueError(f"no gateway handler registered for action={action}")

    await update_agent_run(
        db,
        run_id=context.run_id,
        status="dispatching",
        current_phase="dispatch_gateway",
        summary=f"Dispatch gateway routing {action} via {packet.selected_lane}.",
        final_decision=action,
    )
    await publish_agent_event(
        db,
        run_id=context.run_id,
        project_id=context.project_id,
        user_id=context.user_id,
        source="dispatch_gateway",
        event_type="decision",
        phase="dispatch_gateway",
        title="Authoritative dispatch gateway",
        detail=f"{action} -> {packet.selected_lane}",
        status="dispatching",
        progress=55,
        meta={"decision_packet": packet.as_dict(), "mission": mission, "run_mode": context.run_mode},
        event_kind="decision",
        visibility="debug",
        summary=f"Dispatch {action}",
        reason=packet.reason,
    )
    await main_chain_feedback.publish_runtime_feedback(
        db,
        run_id=context.run_id,
        project_id=context.project_id,
        user_id=context.user_id,
        feedback=RuntimeFeedback(
            status="executing",
            summary=f"Dispatching {action} through {lane}.",
            next_step="Wait for the assigned worker or provider result, then verify writeback.",
            evidence=packet.evidence_refs,
            risk=packet.risk,
        ),
    )

    result = dict(await handler())
    result.setdefault("run_id", context.run_id)
    result["decision_packet"] = packet.as_dict()
    await decision_mailbox.complete_decision(
        db,
        run_id=context.run_id,
        project_id=context.project_id,
        user_id=context.user_id,
        decision_id=decision_id,
        result_ref={key: value for key, value in result.items() if key != "decision_packet"},
    )
    return result


def _validate_packet(packet: DecisionTickResult) -> dict[str, Any]:
    if packet.status != "execute" or not packet.dispatchable or not packet.allowed:
        raise ValueError(f"packet is not dispatchable: status={packet.status} dispatchable={packet.dispatchable}")
    mission = dict(packet.mission or {})
    for key in ("mission_id", "lane", "action", "write_scope", "idempotency_key"):
        if not mission.get(key):
            raise ValueError(f"decision packet mission missing {key}")
    if str(mission["lane"]) not in {"a_lane_project_brain", "b_lane_agent_runs", "c_lane_production"}:
        raise ValueError(f"unsupported mission lane={mission['lane']}")
    if not isinstance(mission.get("write_scope"), list) or not mission["write_scope"]:
        raise ValueError("decision packet mission requires a non-empty write_scope")
    return mission


def _capability_for_action(action: str) -> str:
    from app.services.action_registry import capability_for_action
    if action in {"export_preview", "export_final"}:
        return "execute_assigned_mission"
    return capability_for_action(action)
