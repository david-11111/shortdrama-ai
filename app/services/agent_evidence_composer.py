from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.services.agent_control_registry import COMPOSER_ACTIONS
from app.services.credits import credit_service


logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class EvidenceComposition:
    reply: str
    recommended_action: str
    dispatch_ready: bool
    reason: str
    needs_human: bool
    source: str = "deepseek"

    def as_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "recommended_action": self.recommended_action,
            "dispatch_ready": self.dispatch_ready,
            "reason": self.reason,
            "needs_human": self.needs_human,
            "source": self.source,
        }


async def compose_evidence_reply(
    *,
    instruction: str,
    tool_result: dict[str, Any],
    fallback_reply: str,
    allowed_actions: list[str] | None = None,
    gate: dict[str, Any] | None = None,
    recent_human_events: list[dict[str, Any]] | None = None,
    user_id: int | None = None,
) -> EvidenceComposition | None:
    settings = get_settings()
    provider = (settings.llm_planner_provider or "auto").strip().lower()
    if provider not in {"auto", "deepseek"}:
        return None
    if not settings.deepseek_api_key:
        return None
    try:
        return await _compose_with_deepseek(
            instruction=instruction,
            tool_result=tool_result,
            fallback_reply=fallback_reply,
            allowed_actions=allowed_actions or [],
            gate=gate or {},
            recent_human_events=recent_human_events or [],
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning("DeepSeek evidence composer failed; using deterministic reply: %s", exc)
        return None


async def _compose_with_deepseek(
    *,
    instruction: str,
    tool_result: dict[str, Any],
    fallback_reply: str,
    allowed_actions: list[str],
    gate: dict[str, Any],
    recent_human_events: list[dict[str, Any]],
    user_id: int | None = None,
) -> EvidenceComposition | None:
    settings = get_settings()
    system_prompt = (
        "You are DeepSeek Evidence Composer inside a Codex-style controller. "
        "Do not classify the whole task and do not invent facts. You only read tool_result and produce a user-facing Chinese reply. "
        "Never expose internal JSON, routing, confidence, dispatch_ready, schema, or debug labels to the user. "
        "Use a direct engineering assistant tone: state what was checked, what the evidence shows, and what should happen next. "
        "recommended_action must be one of allowed_actions. If no action is safe, use empty string. "
        "dispatch_ready=true only if the recommended action is concrete, allowed, and does not require missing human details. "
        "Return JSON only with keys: reply, recommended_action, dispatch_ready, reason, needs_human."
    )
    user_payload = {
        "instruction": instruction,
        "tool_result": tool_result,
        "fallback_reply": fallback_reply,
        "allowed_actions": allowed_actions,
        "gate": gate,
        "recent_human_events": recent_human_events[-5:],
    }
    request_body = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
        ],
        "temperature": 0.1,
        "max_tokens": 600,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
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
    if user_id is not None:
        usage = data.get("usage") or {}
        token_count = usage.get("total_tokens", 0)
        if token_count > 0:
            try:
                await credit_service.charge_direct(
                    user_id=user_id,
                    operation="llm_planner_call",
                    token_count=token_count,
                    ref_id=f"llm:evcom:{instruction.strip()[:40]}",
                )
            except Exception:
                logger.warning("Failed to charge LLM tokens (non-blocking)", exc_info=True)
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    parsed = json.loads(content)
    return composition_from_payload(parsed, allowed_actions=allowed_actions)


def composition_from_payload(payload: dict[str, Any], *, allowed_actions: list[str]) -> EvidenceComposition | None:
    reply = str(payload.get("reply") or "").strip()
    if not reply:
        return None
    allowed = {str(action) for action in allowed_actions}
    recommended_action = str(payload.get("recommended_action") or "").strip()
    if recommended_action not in COMPOSER_ACTIONS:
        recommended_action = ""
    if recommended_action and allowed and recommended_action not in allowed:
        recommended_action = ""
    dispatch_ready = _bool_value(payload.get("dispatch_ready")) and bool(recommended_action)
    needs_human = _bool_value(payload.get("needs_human"))
    return EvidenceComposition(
        reply=reply,
        recommended_action=recommended_action,
        dispatch_ready=dispatch_ready,
        reason=str(payload.get("reason") or "").strip(),
        needs_human=needs_human,
    )


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)
