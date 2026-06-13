from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.services.action_registry import registered_planner_actions
from app.services.credits import credit_service


logger = logging.getLogger(__name__)

PLANNER_ACTIONS = registered_planner_actions()


@dataclass(frozen=True)
class PlannerDecision:
    action: str
    confidence: float
    reason: str
    target: dict[str, Any]
    source: str
    intent_type: str = "production_action"
    reply: str = ""
    dispatch_ready: bool = True
    missing_info: list[str] | None = None
    extracted: dict[str, Any] | None = None
    decision_rationale: str = ""
    root_cause_layer: str = ""
    evidence_refs: list[dict[str, Any]] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "confidence": self.confidence,
            "reason": self.reason,
            "target": self.target,
            "source": self.source,
            "intent_type": self.intent_type,
            "reply": self.reply,
            "dispatch_ready": self.dispatch_ready,
            "missing_info": list(self.missing_info or []),
            "extracted": self.extracted or {},
            "decision_rationale": self.decision_rationale,
            "root_cause_layer": self.root_cause_layer,
            "evidence_refs": list(self.evidence_refs or []),
        }


async def plan_human_instruction(
    instruction: str,
    *,
    project_context: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> PlannerDecision | None:
    settings = get_settings()
    provider = (settings.llm_planner_provider or "auto").strip().lower()
    if provider not in {"auto", "deepseek"}:
        return None
    if not settings.deepseek_api_key:
        return None
    try:
        return await _plan_with_deepseek(instruction, project_context=project_context or {}, user_id=user_id)
    except Exception as exc:
        logger.warning("DeepSeek planner failed; falling back to rule routing: %s", exc)
        return None


async def _plan_with_deepseek(
    instruction: str,
    *,
    project_context: dict[str, Any],
    user_id: int | None = None,
) -> PlannerDecision | None:
    settings = get_settings()
    system_prompt = (
        "You are DeepSeek, the conversation-first director controller for an AI short-drama production run. "
        "You must talk to the user before routing work. Convert the user's Chinese or English instruction into one JSON object. "
        "Allowed actions: status_query, generate_story_plan, plan_visual_assets, generate_keyframes, generate_videos, plan_final_edit. "
        "First classify intent_type as one of: conversation, status_query, ui_diagnostic, production_action, quality_feedback. "
        "Write reply like a senior product/debugging copilot in concise Chinese: direct, specific, not a router log, no repeated 'you mentioned'. "
        "Never expose internal labels such as intent_type, dispatch_ready, confidence, routing, action_hint, or JSON. "
        "If the user reports missing/broken/not visible output assets, there is enough information to inspect the current run unless they ask to modify the asset itself. "
        "For those display/output diagnostics, set intent_type=ui_diagnostic, action=status_query, dispatch_ready=true, and reply should say you will inspect the output snapshot, stored URLs, empty shot rows, and browser-load likely causes; do not ask which images first. "
        "If the user says to restore, fill in,补上,修复,重新补齐, or regenerate previously missing reference images/keyframes and says prompts already exist, treat it as an executable production repair: set intent_type=production_action, action=generate_keyframes, dispatch_ready=true. "
        "Default to dispatch_ready=true when the production gap is clear and universal: ALL shots missing images → generate_keyframes; ALL shots have images but no videos → generate_videos; ALL media ready → plan_final_edit. DeepSeek's reasoning is trusted to identify these patterns. "
        "Set dispatch_ready=false ONLY when there is genuine ambiguity the user must resolve: which specific shot to regenerate, what visual change is desired, or a choice between two valid production paths. "
        "When dispatch_ready=false, ask one concise follow-up and preserve any extracted facts. "
        "Use intent_type=status_query for questions about progress, status, who is handling a step, or what is happening now; normally dispatch_ready=false. "
        "Use intent_type=ui_diagnostic for questions or complaints about outputs being missing, broken, not displaying, not visible, blank, expired, inaccessible, or whether a generated asset can be inspected. "
        "Use plan_visual_assets for reference images, visual assets, characters, scenes, products, props, costumes, or Seedream. "
        "If the user asks for 剪辑, 配音, 字幕, 音乐, BGM, 成片, 导出, final cut, or export, prefer action=plan_final_edit; phrases like 根据剧本情况 mean the existing script/storyboard is context, not a request to regenerate the script. "
        "If action_hint is present, treat it as a UI hint, not a command; override it when the user's sentence is actually a question or diagnostic. "
        "--- Internal audit fields (never exposed to user) --- "
        "root_cause_layer: classify the bottleneck layer as one of shot | asset | provider | script | workflow | none. "
        "shot = shot/storyboard row is missing or underspecified; asset = media file missing/broken/expired; provider = external API saturation or error; script = story/script level issue; workflow = pipeline orchestration gap; none = normal operation. "
        "decision_rationale: a concise Chinese sentence summarizing WHY this action was chosen, what bottleneck was diagnosed, and what evidence supports it. This is an internal audit trail, not user-facing. "
        "evidence_refs: list of {kind, key} objects referencing the specific data that informed this decision (e.g. shot_index, task_id, run_id, provider_name, error_category). "
        "Return JSON only with keys: reply, intent_type, dispatch_ready, action, confidence, reason, target, missing_info, extracted, root_cause_layer, decision_rationale, evidence_refs. Do not execute anything."
    )
    user_payload = {
        "instruction": instruction,
        "project_context": project_context,
    }
    request_body = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
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
                    ref_id=f"llm:planner:{instruction.strip()[:40]}",
                )
            except Exception:
                logger.warning("Failed to charge LLM tokens (non-blocking)", exc_info=True)
    raw = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    parsed = _extract_json_object(raw)
    action = str(parsed.get("action") or "").strip()
    intent_type = _normalize_intent_type(parsed.get("intent_type"), action=action)
    dispatch_ready = _dispatch_ready(parsed.get("dispatch_ready"), intent_type=intent_type, action=action)
    if action not in PLANNER_ACTIONS and (action or dispatch_ready):
        return None
    confidence = _bounded_confidence(parsed.get("confidence"))
    target = parsed.get("target") if isinstance(parsed.get("target"), dict) else {}
    missing_info = parsed.get("missing_info") if isinstance(parsed.get("missing_info"), list) else []
    extracted = parsed.get("extracted") if isinstance(parsed.get("extracted"), dict) else {}
    decision_rationale = str(parsed.get("decision_rationale") or "").strip()
    root_cause_layer = _normalize_root_cause(parsed.get("root_cause_layer"))
    evidence_refs = parsed.get("evidence_refs") if isinstance(parsed.get("evidence_refs"), list) else []
    evidence_refs = [ref for ref in evidence_refs if isinstance(ref, dict)]
    return PlannerDecision(
        action=action,
        confidence=confidence,
        reason=str(parsed.get("reason") or ""),
        target=target,
        source="deepseek",
        intent_type=intent_type,
        reply=str(parsed.get("reply") or ""),
        dispatch_ready=dispatch_ready,
        missing_info=[str(item) for item in missing_info if str(item).strip()],
        extracted=extracted,
        decision_rationale=decision_rationale,
        root_cause_layer=root_cause_layer,
        evidence_refs=evidence_refs,
    )


def _bounded_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _normalize_intent_type(value: Any, *, action: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"conversation", "status_query", "ui_diagnostic", "production_action", "quality_feedback"}:
        return raw
    if action == "status_query":
        return "status_query"
    return "production_action"


def _dispatch_ready(value: Any, *, intent_type: str, action: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"true", "1", "yes", "y"}:
            return True
        if raw in {"false", "0", "no", "n"}:
            return False
    if value is None:
        return bool(action and intent_type in {"production_action", "quality_feedback"})
    return bool(value)


_VALID_ROOT_CAUSE_LAYERS = {"shot", "asset", "provider", "script", "workflow", "none"}


def _normalize_root_cause(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in _VALID_ROOT_CAUSE_LAYERS:
        return raw
    return ""


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Fault-tolerant JSON extraction: handles text before/after the JSON block."""
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return {}
    candidate = text[start : end + 1]
    try:
        result = json.loads(candidate)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("DeepSeek planner returned unparseable content: %.200s", raw)
        return {}
