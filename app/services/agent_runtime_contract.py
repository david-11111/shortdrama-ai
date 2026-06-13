from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.services.agent_control_registry import CAPABILITY_REGISTRY, CONTROL_DIAGNOSTIC_TOOLS


RuntimeDecisionKind = Literal["inspect", "execute", "defer", "reject", "ask"]


@dataclass(frozen=True)
class RuntimeDecision:
    kind: RuntimeDecisionKind
    action: str = ""
    capability: str = ""
    user_message: str = ""
    reason: str = ""
    allowed: bool = True
    needs_human: bool = False
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)

    def as_dict(self, *, include_debug: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "action": self.action,
            "capability": self.capability,
            "allowed": self.allowed,
            "needs_human": self.needs_human,
            "user_message": self.user_message,
            "reason": self.reason,
            "evidence_refs": self.evidence_refs,
        }
        if include_debug:
            payload["debug"] = self.debug
        return payload


def decide_runtime_action(
    *,
    routing: dict[str, Any],
    active_tasks: dict[str, Any],
    current_status: str,
) -> RuntimeDecision:
    """Normalize model/controller intent into the service-side runtime contract.

    DeepSeek can suggest intent and wording, but this function is the hard
    boundary that decides whether the server will inspect, execute, defer,
    reject, or ask the user for more information.
    """

    planner = routing.get("planner") if isinstance(routing.get("planner"), dict) else {}
    action = _resolved_action(routing)
    tool_name = str((routing.get("control_tool") or {}).get("tool_name") or "")
    intent_type = str(routing.get("intent_type") or "")
    action_ceiling = str(routing.get("action_ceiling") or (routing.get("utterance") or {}).get("action_ceiling") or "")
    utterance_type = str(routing.get("utterance_type") or (routing.get("utterance") or {}).get("utterance_type") or "")
    active_count = int(active_tasks.get("count") or 0)
    debug = {
        "intent_type": intent_type,
        "utterance_type": utterance_type,
        "action_ceiling": action_ceiling,
        "tool_name": tool_name,
        "planner_dispatch_ready": planner.get("dispatch_ready"),
        "active_task_count": active_count,
        "current_status": current_status,
    }

    if current_status == "cancelled":
        return RuntimeDecision(
            kind="reject",
            action=action,
            capability=action,
            allowed=False,
            user_message="当前 run 已取消，不能继续执行。",
            reason="run_cancelled",
            debug=debug,
        )

    if action_ceiling == "inspect_only":
        return RuntimeDecision(
            kind="inspect",
            action="status_query",
            capability="status_query",
            allowed=True,
            user_message="先检查服务端证据，再基于结果答复；当前输入不能直接派发生产任务。",
            reason="inspect_only_ceiling",
            debug=debug,
        )

    if action_ceiling == "pending_confirm" and not routing.get("pending_action"):
        return RuntimeDecision(
            kind="ask",
            action=action,
            capability="conversation",
            allowed=True,
            needs_human=True,
            user_message="我没有找到上一条待确认动作。请直接说明要执行哪一步。",
            reason="pending_confirm_without_pending_action",
            debug=debug,
        )

    if planner and not bool(planner.get("dispatch_ready")) and not routing.get("controller_intent") and not routing.get("state_machine_recovery"):
        return RuntimeDecision(
            kind="ask",
            action=action,
            capability="conversation",
            allowed=True,
            needs_human=True,
            user_message=str(planner.get("reply") or "我需要先确认更多信息，再决定是否派发生产任务。"),
            reason=str(planner.get("reason") or "planner_requires_human_clarification"),
            debug=debug,
        )

    if intent_type in {"ui_diagnostic", "status_query"} or tool_name in CONTROL_DIAGNOSTIC_TOOLS or action == "status_query":
        return RuntimeDecision(
            kind="inspect",
            action=action or "status_query",
            capability="status_query",
            allowed=True,
            user_message="先检查服务端证据，再基于结果答复。",
            reason="diagnostic_or_status_request",
            debug=debug,
        )

    if active_count > 0:
        return RuntimeDecision(
            kind="defer",
            action=action or "brain_next",
            capability=action or "brain_next",
            allowed=True,
            user_message=f"当前已有 {active_count} 个任务正在执行，指令已暂存，等待当前任务完成后再继续。",
            reason="busy_gate",
            debug=debug,
        )

    if action and action not in CAPABILITY_REGISTRY:
        return RuntimeDecision(
            kind="reject",
            action=action,
            capability="",
            allowed=False,
            user_message="当前动作不在中控能力白名单中，不能自动执行。",
            reason="capability_not_registered",
            debug=debug,
        )

    return RuntimeDecision(
        kind="execute",
        action=action or "brain_next",
        capability=action if action in CAPABILITY_REGISTRY else "project_brain",
        allowed=True,
        user_message="状态机允许且当前没有活动任务，进入执行环节。",
        reason="idle_and_allowed",
        debug=debug,
    )


def public_capability(action: str) -> dict[str, Any]:
    capability = CAPABILITY_REGISTRY.get(action)
    if not capability:
        return {}
    return {
        "version": capability.get("version"),
        "kind": capability.get("kind"),
        "risk_level": capability.get("risk_level"),
        "auto_execute_policy": capability.get("auto_execute_policy"),
        "required_permission": capability.get("required_permission"),
        "gate_rules": capability.get("gate_rules") or [],
        "verify": capability.get("verify") or [],
    }


def _resolved_action(routing: dict[str, Any]) -> str:
    return str(routing.get("resolved_action") or routing.get("action") or "").strip()
